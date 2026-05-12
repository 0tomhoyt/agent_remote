from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path

from agent_remote.models import CommandSpec, JobManifest, JobStatus, new_job_id
from agent_remote.relay import RelayStore
from agent_remote.runner import Runner
from agent_remote.util import artifact_ref


class RelayRunnerTests(unittest.TestCase):
    def test_successful_job_collects_logs_and_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._make_artifact(
                root,
                {
                    "run_case.sh": (
                        "echo stdout-$1\n"
                        "echo stderr-$1 >&2\n"
                        "echo '{\"ok\": true}' > result.json\n"
                    )
                },
            )
            relay = RelayStore(root / "relay")
            manifest = JobManifest(
                job_id=new_job_id(),
                target="exec-a",
                artifact=artifact_ref(artifact),
                command=CommandSpec(argv=["sh", "run_case.sh", "case_001"], timeout_sec=10),
                collect=["result.json"],
            )

            relay.submit(manifest, artifact)
            runner = Runner(relay, target="exec-a", work_root=root / "worker", runner_id="test-runner")

            self.assertEqual(runner.run_once(), manifest.job_id)

            finished = relay.read_manifest(manifest.job_id)
            self.assertEqual(finished.status, JobStatus.SUCCEEDED)
            self.assertEqual(finished.exit_code, 0)
            self.assertIn("stdout-case_001", relay.read_log(manifest.job_id, "stdout.log"))
            self.assertIn("stderr-case_001", relay.read_log(manifest.job_id, "stderr.log"))
            self.assertTrue((relay.result_path(manifest.job_id) / "collected" / "result.json").exists())

            out = root / "fetched"
            relay.fetch_results(manifest.job_id, out)
            self.assertTrue((out / "meta.json").exists())

    def test_timeout_job_is_marked_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._make_artifact(
                root,
                {
                    "slow.py": "import time\ntime.sleep(2)\n",
                },
            )
            relay = RelayStore(root / "relay")
            manifest = JobManifest(
                job_id=new_job_id(),
                target="exec-a",
                artifact=artifact_ref(artifact),
                command=CommandSpec(argv=["python3", "slow.py"], timeout_sec=1),
            )

            relay.submit(manifest, artifact)
            runner = Runner(relay, target="exec-a", work_root=root / "worker", runner_id="test-runner")
            runner.run_once()

            finished = relay.read_manifest(manifest.job_id)
            self.assertEqual(finished.status, JobStatus.TIMEOUT)
            self.assertIn("timed out", finished.error or "")

    @staticmethod
    def _make_artifact(root: Path, files: dict[str, str]) -> Path:
        package_dir = root / "package-src"
        package_dir.mkdir()
        for name, content in files.items():
            path = package_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        artifact = root / "op_package.tar.gz"
        with tarfile.open(artifact, "w:gz") as archive:
            for path in package_dir.rglob("*"):
                archive.add(path, arcname=path.relative_to(package_dir))
        return artifact


if __name__ == "__main__":
    unittest.main()
