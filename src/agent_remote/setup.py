"""Interactive setup wizard for agent-remote deployment.

Requires paramiko (optional dependency). Install with:
    pip install paramiko
"""
from __future__ import annotations

import json
import socket
import sys
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any, Callable

from .config import DEFAULT_RELAY_STORAGE_ROOT, DEFAULT_WORK_ROOT
from .http_relay import create_http_relay_server


@dataclass
class HostCredentials:
    user: str
    host: str
    password: str
    port: int = 22

    @classmethod
    def parse(cls, spec: str, password: str, port: int = 22) -> HostCredentials:
        if "@" not in spec:
            raise ValueError(f"expected user@host format, got: {spec}")
        user, host = spec.split("@", 1)
        return cls(user=user, host=host, password=password, port=port)

    @property
    def ssh_host(self) -> str:
        return f"{self.user}@{self.host}"


@dataclass
class SetupConfig:
    build_host: HostCredentials
    exec_host: HostCredentials
    target_name: str = "exec-a"
    relay_port: int = 8080
    remote_python: str = "python3"
    install_method: str = "pip"
    skip_relay_start: bool = False


class SSHConnection:
    def __init__(
        self,
        creds: HostCredentials,
        client_factory: Callable[..., Any] | None = None,
    ):
        self._creds = creds
        self._client_factory = client_factory
        self._client: Any = None
        self._sftp: Any = None

    def __enter__(self) -> SSHConnection:
        try:
            import paramiko
        except ImportError:
            raise RuntimeError(
                "paramiko is required for setup. Install it with:\n"
                "  pip install paramiko"
            )
        factory = self._client_factory or paramiko.SSHClient
        self._client = factory()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=self._creds.host,
            port=self._creds.port,
            username=self._creds.user,
            password=self._creds.password,
        )
        self._sftp = self._client.open_sftp()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._sftp:
            self._sftp.close()
        if self._client:
            self._client.close()

    def run(self, command: str, check: bool = True) -> tuple[int, str, str]:
        assert self._client is not None
        stdin, stdout, stderr = self._client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if check and exit_code != 0:
            raise RuntimeError(
                f"SSH command failed on {self._creds.ssh_host}: "
                f"exit_code={exit_code}\nstdout: {out}\nstderr: {err}"
            )
        return exit_code, out, err

    def put_file(self, local_path: Path, remote_path: str) -> None:
        assert self._sftp is not None
        self._sftp.put(str(local_path), remote_path)

    def put_content(self, content: str, remote_path: str) -> None:
        assert self._sftp is not None
        with self._sftp.open(remote_path, "w") as f:
            f.write(content)


def run_setup(args: Any) -> int:
    try:
        import paramiko  # noqa: F401
    except ImportError:
        print(
            "error: paramiko is required for setup. Install it with:\n"
            "  pip install paramiko",
            file=sys.stderr,
        )
        return 2

    setup_cfg = _build_config(args)

    try:
        _run_setup_steps(setup_cfg)
    except KeyboardInterrupt:
        print("\nsetup interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _build_config(args: Any) -> SetupConfig:
    if args.build_host and args.exec_host:
        build_creds = HostCredentials.parse(
            args.build_host, args.build_password or ""
        )
        exec_creds = HostCredentials.parse(
            args.exec_host, args.exec_password or ""
        )
        return SetupConfig(
            build_host=build_creds,
            exec_host=exec_creds,
            target_name=args.target_name,
            relay_port=args.relay_port,
            remote_python=args.remote_python,
            install_method=args.install_method,
            skip_relay_start=args.skip_relay_start,
        )
    return _gather_credentials_interactive()


def _gather_credentials_interactive() -> SetupConfig:
    print("=== agent-remote setup ===\n")

    print("--- Build Host (compilation machine) ---")
    build_spec = input("SSH host (user@ip): ").strip()
    build_password = getpass("SSH password: ")

    print("\n--- Execution Host (test/benchmark machine) ---")
    exec_spec = input("SSH host (user@ip): ").strip()
    exec_password = getpass("SSH password: ")

    print("\n--- Options ---")
    target_name = input("Target name [exec-a]: ").strip() or "exec-a"
    relay_port_str = input("Relay port [8080]: ").strip() or "8080"
    relay_port = int(relay_port_str)
    remote_python = input("Remote Python [python3]: ").strip() or "python3"

    build_creds = HostCredentials.parse(build_spec, build_password)
    exec_creds = HostCredentials.parse(exec_spec, exec_password)

    print(f"\n--- Summary ---")
    print(f"Build host: {build_creds.ssh_host}")
    print(f"Exec host:  {exec_creds.ssh_host}")
    print(f"Relay:      0.0.0.0:{relay_port}")
    print(f"Target:     {target_name}")

    confirm = input("\nProceed? [Y/n]: ").strip().lower()
    if confirm and confirm != "y":
        print("aborted.")
        raise SystemExit(0)

    return SetupConfig(
        build_host=build_creds,
        exec_host=exec_creds,
        target_name=target_name,
        relay_port=relay_port,
        remote_python=remote_python,
    )


def _run_setup_steps(setup_cfg: SetupConfig) -> None:
    relay_ip = detect_local_ip(setup_cfg.build_host.host)
    print(f"Detected relay IP: {relay_ip}\n")

    total_steps = 5
    step = 0

    # Step 1: Build host - check Python
    step += 1
    print(f"[{step}/{total_steps}] Checking build host Python...")
    with SSHConnection(setup_cfg.build_host) as conn:
        python_path, build_python = _check_python(conn, setup_cfg.remote_python)
        print(f"  {python_path} OK")

        # Step 2: Build host - install agent_remote
        step += 1
        print(f"[{step}/{total_steps}] Installing agent_remote on build host...")
        _install_remote(conn, setup_cfg.install_method, build_python)
        print("  OK")

        # Step 3: Push build host config
        build_config = generate_build_host_config(setup_cfg, relay_ip)
        push_config(conn, build_config, "~/.agent-remote/config.json")
        print("  Build host config pushed.")

    # Step 4: Exec host - check Python + install
    step += 1
    print(f"[{step}/{total_steps}] Checking execution host Python...")
    with SSHConnection(setup_cfg.exec_host) as conn:
        python_path, exec_python = _check_python(conn, setup_cfg.remote_python)
        print(f"  {python_path} OK")

        step += 1
        print(f"[{step}/{total_steps}] Installing agent_remote on execution host...")
        _install_remote(conn, setup_cfg.install_method, exec_python)
        print("  OK")

        # Push exec host config
        exec_config = generate_exec_host_config(setup_cfg, relay_ip)
        push_config(conn, exec_config, "~/.agent-remote/config.json")
        print("  Execution host config pushed.")

    # Step 5: Write local relay config and start
    step += 1
    print(f"[{step}/{total_steps}] Writing local relay config...")
    start_relay_server(setup_cfg)


def _check_python(conn: SSHConnection, remote_python: str) -> tuple[str, str]:
    """Return (display_string, actual_python_name)."""
    exit_code, out, err = conn.run(f"{remote_python} --version", check=False)
    resolved = remote_python
    if exit_code != 0:
        for fallback in ("python3", "python"):
            if fallback == remote_python:
                continue
            exit_code, out, err = conn.run(f"{fallback} --version", check=False)
            if exit_code == 0:
                resolved = fallback
                break
        else:
            raise RuntimeError(
                f"Python not found on {conn._creds.ssh_host}. "
                "Please install Python 3.10+ first."
            )

    version_str = out.strip().split()[-1]
    parts = version_str.split(".")
    major, minor = int(parts[0]), int(parts[1])
    if major < 3 or (major == 3 and minor < 10):
        raise RuntimeError(
            f"Python {version_str} on {conn._creds.ssh_host} is too old. "
            "Need Python 3.10+."
        )
    return f"{resolved} ({version_str})", resolved


def _install_remote(conn: SSHConnection, method: str, remote_python: str) -> None:
    # Check if already installed
    exit_code, _, _ = conn.run(
        f"{remote_python} -m agent_remote.cli --help", check=False
    )
    if exit_code == 0:
        print("  agent_remote already installed, skipping.")
        return

    if method == "pip":
        _install_via_pip(conn, remote_python)
    else:
        _install_via_git(conn, remote_python)

    # Verify
    conn.run(f"{remote_python} -m agent_remote.cli --help")


def _install_via_pip(conn: SSHConnection, remote_python: str) -> None:
    exit_code, out, err = conn.run(
        f"{remote_python} -m pip install agent-remote", check=False
    )
    if exit_code != 0:
        # Fallback to git URL
        exit_code, out, err = conn.run(
            f"{remote_python} -m pip install git+https://github.com/0tomhoyt/agent_remote.git",
            check=False,
        )
        if exit_code != 0:
            raise RuntimeError(
                f"pip install failed on {conn._creds.ssh_host}:\n{err}"
            )


def _install_via_git(conn: SSHConnection, remote_python: str) -> None:
    conn.run(
        "git clone https://github.com/0tomhoyt/agent_remote.git "
        "/tmp/agent_remote",
        check=False,
    )
    conn.run(f"{remote_python} -m pip install -e /tmp/agent_remote")


def generate_build_host_config(setup_cfg: SetupConfig, relay_ip: str) -> dict:
    return {
        "targets": {
            setup_cfg.target_name: {
                "relay_url": f"http://{relay_ip}:{setup_cfg.relay_port}",
                "default_timeout_sec": 600,
            }
        },
        "profiles": {},
    }


def generate_exec_host_config(setup_cfg: SetupConfig, relay_ip: str) -> dict:
    return {
        "targets": {
            setup_cfg.target_name: {
                "relay_url": f"http://{relay_ip}:{setup_cfg.relay_port}",
                "work_root": DEFAULT_WORK_ROOT,
                "default_timeout_sec": 600,
            }
        },
        "profiles": {},
    }


def generate_relay_config(setup_cfg: SetupConfig) -> dict:
    return {
        "relay_server": {
            "host": "0.0.0.0",
            "port": setup_cfg.relay_port,
            "storage_root": DEFAULT_RELAY_STORAGE_ROOT,
        }
    }


def push_config(conn: SSHConnection, config_data: dict, remote_path: str) -> None:
    content = json.dumps(config_data, indent=2, sort_keys=True) + "\n"
    parent = str(Path(remote_path).parent)
    conn.run(f"mkdir -p {parent}")
    conn.put_content(content, remote_path)


def detect_local_ip(target_host: str) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target_host, 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def start_relay_server(setup_cfg: SetupConfig) -> None:
    local_config_dir = Path(".agent-remote")
    local_config_dir.mkdir(parents=True, exist_ok=True)
    config_data = generate_relay_config(setup_cfg)
    (local_config_dir / "config.json").write_text(
        json.dumps(config_data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if setup_cfg.skip_relay_start:
        print("  Relay config written. Skipping relay start (--skip-relay-start).")
        return

    server = create_http_relay_server(
        "0.0.0.0", setup_cfg.relay_port, DEFAULT_RELAY_STORAGE_ROOT
    )
    print(f"\nrelay server listening on http://0.0.0.0:{setup_cfg.relay_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
