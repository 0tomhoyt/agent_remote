from __future__ import annotations

import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from agent_remote.models import CommandSpec, JobManifest, JobStatus, new_job_id
from agent_remote.relay import RelayStore
from agent_remote.ssh_transport import SSHDirectTransport
from agent_remote.util import artifact_ref, atomic_write_json


class SSHDirectTransportTests(unittest.TestCase):
    def test_ssh_direct_transport_copies_job_runs_worker_and_fetches_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._make_artifact(root)
            relay = RelayStore(root / "relay")
            manifest = JobManifest(
                job_id=new_job_id(),
                target="exec-a",
                artifact=artifact_ref(artifact),
                command=CommandSpec(argv=["sh", "run_case.sh"], timeout_sec=10),
            )
            relay.submit(manifest, artifact)
            fake = FakeCommandRunner(manifest)
            transport = SSHDirectTransport(
                host="user@exec-host",
                port=2222,
                remote_relay_root="/tmp/agent-remote/relay",
                remote_work_root="/tmp/agent-remote/worker",
                runner=fake,
            )

            finished = transport.run_job(relay, manifest)

            self.assertEqual(finished.status, JobStatus.SUCCEEDED)
            self.assertEqual(finished.exit_code, 0)
            self.assertTrue((relay.result_path(manifest.job_id) / "meta.json").exists())
            self.assertTrue(any(command[0] == "ssh" for command in fake.commands))
            self.assertTrue(any("agent_remote.cli" in command for command in fake.commands))
            self.assertTrue(any(command[0] == "scp" for command in fake.commands))

    @staticmethod
    def _make_artifact(root: Path) -> Path:
        package_dir = root / "package-src"
        package_dir.mkdir()
        (package_dir / "run_case.sh").write_text("echo ok\n", encoding="utf-8")
        artifact = root / "op_package.tar.gz"
        with tarfile.open(artifact, "w:gz") as archive:
            for path in package_dir.rglob("*"):
                archive.add(path, arcname=path.relative_to(package_dir))
        return artifact


class FakeCommandRunner:
    def __init__(self, manifest: JobManifest):
        self.manifest = manifest
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        self.commands.append(argv)
        if argv[0] == "scp" and argv[-2].endswith(f"/results/{self.manifest.job_id}"):
            dest = Path(argv[-1])
            dest.mkdir(parents=True)
            (dest / "meta.json").write_text("{}", encoding="utf-8")
        elif argv[0] == "scp" and f"/jobs/done/{self.manifest.job_id}.json" in argv[-2]:
            finished = JobManifest.from_dict(self.manifest.to_dict())
            finished.status = JobStatus.SUCCEEDED
            finished.exit_code = 0
            atomic_write_json(Path(argv[-1]), finished.to_dict())
        elif argv[0] == "scp" and "/jobs/" in argv[-2] and ":" in argv[-2]:
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0)


if __name__ == "__main__":
    unittest.main()
