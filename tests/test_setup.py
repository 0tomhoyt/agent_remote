from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

from agent_remote.setup import (
    HostCredentials,
    SetupConfig,
    generate_build_host_config,
    generate_exec_host_config,
    generate_relay_config,
    push_config,
)


class HostCredentialsTests(unittest.TestCase):
    def test_parse_valid(self) -> None:
        creds = HostCredentials.parse("root@192.168.1.10", "secret")
        self.assertEqual(creds.user, "root")
        self.assertEqual(creds.host, "192.168.1.10")
        self.assertEqual(creds.password, "secret")
        self.assertEqual(creds.port, 22)

    def test_parse_with_port(self) -> None:
        creds = HostCredentials.parse("admin@10.0.0.1", "pw", port=2222)
        self.assertEqual(creds.user, "admin")
        self.assertEqual(creds.host, "10.0.0.1")
        self.assertEqual(creds.port, 2222)

    def test_parse_rejects_no_at(self) -> None:
        with self.assertRaises(ValueError):
            HostCredentials.parse("root", "pw")

    def test_ssh_host_property(self) -> None:
        creds = HostCredentials.parse("user@host", "pw")
        self.assertEqual(creds.ssh_host, "user@host")


class ConfigGenerationTests(unittest.TestCase):
    def _make_setup_config(self) -> SetupConfig:
        return SetupConfig(
            build_host=HostCredentials("u", "10.0.0.1", "pw"),
            exec_host=HostCredentials("u", "10.0.0.2", "pw"),
            target_name="my-target",
            relay_port=9090,
        )

    def test_generate_build_host_config(self) -> None:
        cfg = self._make_setup_config()
        result = generate_build_host_config(cfg, "192.168.1.100")
        self.assertIn("targets", result)
        self.assertIn("my-target", result["targets"])
        target = result["targets"]["my-target"]
        self.assertEqual(target["relay_url"], "http://192.168.1.100:9090")
        self.assertEqual(target["default_timeout_sec"], 600)
        self.assertEqual(result["profiles"], {})

    def test_generate_exec_host_config(self) -> None:
        cfg = self._make_setup_config()
        result = generate_exec_host_config(cfg, "192.168.1.100")
        target = result["targets"]["my-target"]
        self.assertEqual(target["relay_url"], "http://192.168.1.100:9090")
        self.assertIn("work_root", target)
        self.assertEqual(target["default_timeout_sec"], 600)

    def test_generate_relay_config(self) -> None:
        cfg = self._make_setup_config()
        result = generate_relay_config(cfg)
        self.assertIn("relay_server", result)
        rs = result["relay_server"]
        self.assertEqual(rs["host"], "0.0.0.0")
        self.assertEqual(rs["port"], 9090)
        self.assertIn("storage_root", rs)


class PushConfigTests(unittest.TestCase):
    def test_push_config_writes_json(self) -> None:
        mock_conn = MagicMock()
        config_data = {"relay_server": {"host": "0.0.0.0", "port": 8080}}

        push_config(mock_conn, config_data, "~/.agent-remote/config.json")

        mock_conn.run.assert_called_once_with("mkdir -p ~/.agent-remote")
        mock_conn.put_content.assert_called_once()
        call_args = mock_conn.put_content.call_args
        content = call_args[0][0]
        path = call_args[0][1]
        self.assertEqual(path, "~/.agent-remote/config.json")
        parsed = json.loads(content)
        self.assertEqual(parsed["relay_server"]["port"], 8080)


class DetectLocalIpTests(unittest.TestCase):
    def test_returns_nonempty_string(self) -> None:
        from agent_remote.setup import detect_local_ip

        # This will connect to localhost, should return a valid IP
        ip = detect_local_ip("127.0.0.1")
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) > 0)


if __name__ == "__main__":
    unittest.main()
