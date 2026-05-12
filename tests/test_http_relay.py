from __future__ import annotations

import json
import tarfile
import tempfile
import threading
import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path

from agent_remote.cli import main
from agent_remote.http_relay import HTTPRelayClient, create_http_relay_server
from agent_remote.models import CommandSpec, JobManifest, JobStatus, new_job_id
from agent_remote.runner import Runner
from agent_remote.util import artifact_ref


class HTTPRelayTests(unittest.TestCase):
    def test_http_relay_submit_worker_status_logs_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._make_artifact(root)
            try:
                server = create_http_relay_server("127.0.0.1", 0, root / "server")
            except PermissionError as exc:
                self.skipTest(f"local socket bind is not permitted: {exc}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_address[1]}"
                submitter = HTTPRelayClient(url, cache_root=root / "submit-cache")
                worker_relay = HTTPRelayClient(url, cache_root=root / "worker-cache")
                manifest = JobManifest(
                    job_id=new_job_id(),
                    target="exec-a",
                    artifact=artifact_ref(artifact),
                    profile="op-test",
                    command=CommandSpec(argv=["sh", "run_case.sh", "case_001"], timeout_sec=10),
                    collect=["result.json"],
                )

                submitter.submit(manifest, artifact)
                runner = Runner(
                    worker_relay,
                    target="exec-a",
                    work_root=root / "worker",
                    runner_id="http-test-runner",
                    allowed_profiles=["op-test"],
                    allowed_commands=["sh"],
                )

                self.assertEqual(runner.run_once(), manifest.job_id)

                finished = submitter.read_manifest(manifest.job_id)
                self.assertEqual(finished.status, JobStatus.SUCCEEDED)
                self.assertEqual(finished.exit_code, 0)
                self.assertIn("http-case_001", submitter.read_log(manifest.job_id, "stdout.log"))

                out = root / "fetched"
                submitter.fetch_results(manifest.job_id, out)
                self.assertTrue((out / "meta.json").exists())
                result = json.loads((out / "collected" / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["case"], "case_001")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_cli_uses_http_relay_url_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._make_artifact(root)
            try:
                server = create_http_relay_server("127.0.0.1", 0, root / "server")
            except PermissionError as exc:
                self.skipTest(f"local socket bind is not permitted: {exc}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_address[1]}"
                build_config = root / "build.json"
                exec_config = root / "exec.json"
                build_config.write_text(
                    json.dumps(
                        {
                            "targets": {"exec-a": {"relay_url": url}},
                            "profiles": {
                                "op-test": {
                                    "target": "exec-a",
                                    "cmd": "sh run_case.sh cli_case",
                                    "collect": ["result.json"],
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                exec_config.write_text(
                    json.dumps(
                        {
                            "targets": {
                                "exec-a": {
                                    "relay_url": url,
                                    "work_root": str(root / "worker"),
                                    "allowed_commands": ["sh"],
                                    "allowed_profiles": ["op-test"],
                                }
                            },
                            "profiles": {},
                        }
                    ),
                    encoding="utf-8",
                )

                submitted = json.loads(
                    self._run_cli(
                        [
                            "--config",
                            str(build_config),
                            "submit",
                            "--profile",
                            "op-test",
                            "--artifact",
                            str(artifact),
                            "--json",
                        ]
                    )
                )
                job_id = submitted["job_id"]
                self._run_cli(["--config", str(exec_config), "worker", "--target", "exec-a", "--once"])
                status = json.loads(
                    self._run_cli(
                        [
                            "--config",
                            str(build_config),
                            "status",
                            job_id,
                            "--target",
                            "exec-a",
                            "--json",
                        ]
                    )
                )
                self.assertEqual(status["status"], "SUCCEEDED")
                self.assertEqual(status["profile"], "op-test")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    @staticmethod
    def _run_cli(argv: list[str]) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            rc = main(argv)
        if rc != 0:
            raise AssertionError(f"CLI returned {rc}: {argv}")
        return output.getvalue()

    @staticmethod
    def _make_artifact(root: Path) -> Path:
        package_dir = root / "package-src"
        package_dir.mkdir()
        (package_dir / "run_case.sh").write_text(
            "echo http-$1\n"
            "echo \"{\\\"case\\\": \\\"$1\\\"}\" > result.json\n",
            encoding="utf-8",
        )
        artifact = root / "http_package.tar.gz"
        with tarfile.open(artifact, "w:gz") as archive:
            for path in package_dir.rglob("*"):
                archive.add(path, arcname=path.relative_to(package_dir))
        return artifact


if __name__ == "__main__":
    unittest.main()
