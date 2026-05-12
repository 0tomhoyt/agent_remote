from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .models import JobManifest, JobStatus
from .relay import RelayStore, STATUS_DIRS


class CommandRunner(Protocol):
    def __call__(self, argv: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        ...


@dataclass
class SSHDirectTransport:
    host: str
    remote_relay_root: str
    remote_work_root: str
    port: int | None = None
    remote_python: str = "python3"
    runner: CommandRunner = field(default=subprocess.run)

    def run_job(self, relay: RelayStore, manifest: JobManifest) -> JobManifest:
        self._ensure_remote_layout()
        self._copy_job_to_remote(relay, manifest)
        self._run_remote_worker(manifest.target)
        self._copy_job_back(relay, manifest.job_id)
        return relay.read_manifest(manifest.job_id)

    def _ensure_remote_layout(self) -> None:
        directories = [
            f"{self.remote_relay_root}/artifacts",
            f"{self.remote_relay_root}/results",
            *[
                f"{self.remote_relay_root}/jobs/{dirname}"
                for dirname in STATUS_DIRS.values()
            ],
            self.remote_work_root,
        ]
        self._ssh(["mkdir", "-p", *directories])

    def _copy_job_to_remote(self, relay: RelayStore, manifest: JobManifest) -> None:
        artifact = relay.artifact_path(manifest)
        pending = relay.job_path(JobStatus.PENDING, manifest.job_id)
        self._scp_to_remote(artifact, f"{self.remote_relay_root}/artifacts/{artifact.name}")
        self._scp_to_remote(pending, f"{self.remote_relay_root}/jobs/pending/{pending.name}")

    def _run_remote_worker(self, target: str) -> None:
        self._ssh(
            [
                self.remote_python,
                "-m",
                "agent_remote.cli",
                "--relay-root",
                self.remote_relay_root,
                "worker",
                "--target",
                target,
                "--work-root",
                self.remote_work_root,
                "--once",
                "--json",
            ]
        )

    def _copy_job_back(self, relay: RelayStore, job_id: str) -> None:
        result_dir = relay.result_path(job_id)
        if result_dir.exists():
            shutil.rmtree(result_dir)
        result_dir.parent.mkdir(parents=True, exist_ok=True)
        self._scp_from_remote(f"{self.remote_relay_root}/results/{job_id}", result_dir, recursive=True)

        copied = False
        for status, dirname in STATUS_DIRS.items():
            local_path = relay.job_path(status, job_id)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            remote_path = f"{self.remote_relay_root}/jobs/{dirname}/{job_id}.json"
            try:
                self._scp_from_remote(remote_path, local_path, recursive=False)
            except subprocess.CalledProcessError:
                continue
            copied = True
            break
        relay.job_path(JobStatus.PENDING, job_id).unlink(missing_ok=True)
        relay.job_path(JobStatus.RUNNING, job_id).unlink(missing_ok=True)
        if not copied:
            raise FileNotFoundError(f"remote job manifest not found after SSH run: {job_id}")

    def _ssh(self, remote_argv: list[str]) -> subprocess.CompletedProcess[str]:
        return self.runner([*self._ssh_base(), self.host, *remote_argv], check=True)

    def _scp_to_remote(self, local_path: Path, remote_path: str) -> subprocess.CompletedProcess[str]:
        return self.runner([*self._scp_base(), str(local_path), f"{self.host}:{remote_path}"], check=True)

    def _scp_from_remote(
        self,
        remote_path: str,
        local_path: Path,
        recursive: bool,
    ) -> subprocess.CompletedProcess[str]:
        argv = [*self._scp_base()]
        if recursive:
            argv.append("-r")
        argv.extend([f"{self.host}:{remote_path}", str(local_path)])
        return self.runner(argv, check=True)

    def _ssh_base(self) -> list[str]:
        argv = ["ssh"]
        if self.port is not None:
            argv.extend(["-p", str(self.port)])
        return argv

    def _scp_base(self) -> list[str]:
        argv = ["scp"]
        if self.port is not None:
            argv.extend(["-P", str(self.port)])
        return argv
