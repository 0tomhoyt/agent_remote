from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agent_remote.cli import main


class CliTests(unittest.TestCase):
    def test_cli_submit_worker_status_logs_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._make_artifact(root)
            relay = root / "relay"
            worker = root / "worker"

            submit = self._run_cli(
                [
                    "--relay-root",
                    str(relay),
                    "submit",
                    "--target",
                    "exec-a",
                    "--artifact",
                    str(artifact),
                    "--cmd",
                    "sh run_case.sh case_001",
                    "--collect",
                    "result.json",
                    "--json",
                ]
            )
            submitted = json.loads(submit)
            job_id = submitted["job_id"]

            self._run_cli(
                [
                    "--relay-root",
                    str(relay),
                    "worker",
                    "--target",
                    "exec-a",
                    "--work-root",
                    str(worker),
                    "--once",
                ]
            )

            status = self._run_cli(["--relay-root", str(relay), "status", job_id, "--json"])
            status_data = json.loads(status)
            self.assertEqual(status_data["status"], "SUCCEEDED")

            logs = self._run_cli(["--relay-root", str(relay), "logs", job_id])
            self.assertIn("cli-case_001", logs)

            out_dir = root / "fetched"
            self._run_cli(["--relay-root", str(relay), "fetch", job_id, "--out", str(out_dir)])
            self.assertTrue((out_dir / "collected" / "result.json").exists())

    def test_cli_submit_uses_profile_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._make_artifact(root)
            relay = root / "relay"
            config_path = root / "remote-run.json"
            config_path.write_text(
                json.dumps(
                    {
                        "targets": {
                            "exec-a": {
                                "relay_root": str(relay),
                                "default_timeout_sec": 30,
                                "allowed_profiles": ["op-test"],
                            }
                        },
                        "profiles": {
                            "op-test": {
                                "target": "exec-a",
                                "cmd": "sh run_case.sh from_profile",
                                "collect": ["result.json"],
                                "env": {"PROFILE_ENV": "1"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            submit = self._run_cli(
                [
                    "--config",
                    str(config_path),
                    "submit",
                    "--profile",
                    "op-test",
                    "--artifact",
                    str(artifact),
                    "--json",
                ]
            )
            job_id = json.loads(submit)["job_id"]

            self._run_cli(
                [
                    "--config",
                    str(config_path),
                    "worker",
                    "--target",
                    "exec-a",
                    "--work-root",
                    str(root / "worker"),
                    "--once",
                ]
            )
            status = json.loads(
                self._run_cli(
                    [
                        "--config",
                        str(config_path),
                        "status",
                        job_id,
                        "--target",
                        "exec-a",
                        "--json",
                    ]
                )
            )
            self.assertEqual(status["profile"], "op-test")
            self.assertEqual(status["command"]["timeout_sec"], 30)
            self.assertEqual(status["command"]["env"]["PROFILE_ENV"], "1")

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
            "echo cli-$1\n"
            "echo '{\"ok\": true}' > result.json\n",
            encoding="utf-8",
        )
        artifact = root / "cli_package.tar.gz"
        with tarfile.open(artifact, "w:gz") as archive:
            for path in package_dir.rglob("*"):
                archive.add(path, arcname=path.relative_to(package_dir))
        return artifact


if __name__ == "__main__":
    unittest.main()
