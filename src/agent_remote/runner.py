from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

from .models import JobManifest, JobStatus, utc_now
from .relay import RelayStore
from .security import validate_allowed_command, validate_allowed_profile
from .util import atomic_write_json, sha256_file


class Runner:
    def __init__(
        self,
        relay: RelayStore,
        target: str,
        work_root: Path | str,
        runner_id: str | None = None,
        allowed_commands: list[str] | None = None,
        allowed_profiles: list[str] | None = None,
    ):
        self.relay = relay
        self.target = target
        self.work_root = Path(work_root).expanduser().resolve()
        self.runner_id = runner_id or f"{socket.gethostname()}:{os.getpid()}"
        self.allowed_commands = allowed_commands or []
        self.allowed_profiles = allowed_profiles or []
        self.work_root.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> str | None:
        manifest = self.relay.claim_next(self.target, self.runner_id)
        if manifest is None:
            return None
        self._run_manifest(manifest)
        return manifest.job_id

    def _run_manifest(self, manifest: JobManifest) -> None:
        job_root = self.work_root / "jobs" / manifest.job_id
        package_dir = job_root / "package"
        result_dir = job_root / "results"
        if manifest.deploy.clean_before_run and job_root.exists():
            shutil.rmtree(job_root)
        package_dir.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = result_dir / "stdout.log"
        stderr_path = result_dir / "stderr.log"
        status = JobStatus.FAILED
        started = time.monotonic()
        timed_out = False

        try:
            validate_allowed_profile(manifest, self.allowed_profiles)
            validate_allowed_command(manifest, self.allowed_commands)
            self._prepare_artifact(manifest, package_dir)
            self._write_tree(package_dir, result_dir / "tree.txt")
            manifest.timestamps["command_started_at"] = utc_now()
            env = os.environ.copy()
            env.update(manifest.command.env)
            env["AGENT_REMOTE_JOB_ID"] = manifest.job_id
            env["AGENT_REMOTE_ARTIFACT_SHA256"] = manifest.artifact.sha256

            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                try:
                    process = subprocess.Popen(
                        manifest.command.argv,
                        cwd=package_dir,
                        env=env,
                        stdout=stdout,
                        stderr=stderr,
                    )
                    manifest.exit_code = process.wait(timeout=manifest.command.timeout_sec)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.kill()
                    manifest.exit_code = process.wait()
                except FileNotFoundError as exc:
                    manifest.exit_code = 127
                    stderr.write(f"{exc}\n".encode("utf-8"))

            if timed_out:
                status = JobStatus.TIMEOUT
                manifest.error = f"command timed out after {manifest.command.timeout_sec} seconds"
            elif manifest.exit_code == 0:
                status = JobStatus.SUCCEEDED
            else:
                status = JobStatus.FAILED
                manifest.error = f"command exited with code {manifest.exit_code}"

            self._collect_files(package_dir, result_dir / "collected", manifest.collect)
        except Exception as exc:
            manifest.exit_code = manifest.exit_code if manifest.exit_code is not None else 1
            manifest.error = f"{type(exc).__name__}: {exc}"
            with stderr_path.open("ab") as stderr:
                stderr.write(f"\nrunner error: {manifest.error}\n".encode("utf-8"))
        finally:
            duration_sec = round(time.monotonic() - started, 3)
            meta = {
                "job_id": manifest.job_id,
                "target": manifest.target,
                "runner_id": self.runner_id,
                "hostname": socket.gethostname(),
                "status": status.value,
                "exit_code": manifest.exit_code,
                "duration_sec": duration_sec,
                "artifact_sha256": manifest.artifact.sha256,
                "command": manifest.command.argv,
                "profile": manifest.profile,
                "created_at": manifest.created_at,
                "timestamps": manifest.timestamps,
                "error": manifest.error,
            }
            atomic_write_json(result_dir / "meta.json", meta)
            self.relay.finish(manifest, result_dir, status)

    def _prepare_artifact(self, manifest: JobManifest, package_dir: Path) -> None:
        artifact_path = self.relay.artifact_path(manifest)
        if not artifact_path.exists():
            raise FileNotFoundError(f"artifact not found: {artifact_path}")
        actual_sha = sha256_file(artifact_path)
        if actual_sha != manifest.artifact.sha256:
            raise ValueError(
                f"artifact sha256 mismatch: expected {manifest.artifact.sha256}, got {actual_sha}"
            )
        if not manifest.deploy.extract:
            shutil.copy2(artifact_path, package_dir / manifest.artifact.name)
            return
        if tarfile.is_tarfile(artifact_path):
            with tarfile.open(artifact_path) as archive:
                self._safe_extract_tar(archive, package_dir)
        elif zipfile.is_zipfile(artifact_path):
            with zipfile.ZipFile(artifact_path) as archive:
                self._safe_extract_zip(archive, package_dir)
        else:
            shutil.copy2(artifact_path, package_dir / manifest.artifact.name)

    @staticmethod
    def _safe_extract_tar(archive: tarfile.TarFile, dest: Path) -> None:
        dest_resolved = dest.resolve()
        for member in archive.getmembers():
            target = (dest / member.name).resolve()
            if not target.is_relative_to(dest_resolved):
                raise ValueError(f"unsafe tar member path: {member.name}")
        archive.extractall(dest)

    @staticmethod
    def _safe_extract_zip(archive: zipfile.ZipFile, dest: Path) -> None:
        dest_resolved = dest.resolve()
        for member in archive.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest_resolved):
                raise ValueError(f"unsafe zip member path: {member.filename}")
        archive.extractall(dest)

    @staticmethod
    def _collect_files(package_dir: Path, collect_dir: Path, patterns: list[str]) -> None:
        collect_dir.mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            if Path(pattern).is_absolute():
                continue
            matches = glob.glob(str(package_dir / pattern), recursive=True)
            for match in matches:
                src = Path(match)
                if not src.exists():
                    continue
                rel = src.relative_to(package_dir)
                dst = collect_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

    @staticmethod
    def _write_tree(root: Path, out_path: Path, limit: int = 500) -> None:
        lines: list[str] = []
        for index, path in enumerate(sorted(root.rglob("*"))):
            if index >= limit:
                lines.append("... truncated ...")
                break
            rel = path.relative_to(root)
            suffix = "/" if path.is_dir() else ""
            lines.append(f"{rel}{suffix}")
        out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
