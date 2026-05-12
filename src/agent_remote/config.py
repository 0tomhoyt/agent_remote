from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]


DEFAULT_RELAY_ROOT = ".agent-remote/relay"
DEFAULT_WORK_ROOT = ".agent-remote/worker"
DEFAULT_TIMEOUT_SEC = 600


@dataclass
class TargetConfig:
    name: str
    relay_root: str | None = None
    relay_url: str | None = None
    work_root: str | None = None
    default_timeout_sec: int | None = None
    allowed_commands: list[str] = field(default_factory=list)
    allowed_profiles: list[str] = field(default_factory=list)
    ssh_host: str | None = None
    ssh_port: int | None = None
    remote_relay_root: str | None = None
    remote_work_root: str | None = None
    remote_python: str | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any] | None) -> "TargetConfig":
        data = data or {}
        return cls(
            name=name,
            relay_root=_optional_str(data.get("relay_root")),
            relay_url=_optional_str(data.get("relay_url")),
            work_root=_optional_str(data.get("work_root")),
            default_timeout_sec=_optional_int(data.get("default_timeout_sec")),
            allowed_commands=[str(item) for item in data.get("allowed_commands", [])],
            allowed_profiles=[str(item) for item in data.get("allowed_profiles", [])],
            ssh_host=_optional_str(data.get("ssh_host")),
            ssh_port=_optional_int(data.get("ssh_port")),
            remote_relay_root=_optional_str(data.get("remote_relay_root")),
            remote_work_root=_optional_str(data.get("remote_work_root")),
            remote_python=_optional_str(data.get("remote_python")),
        )


@dataclass
class ProfileConfig:
    name: str
    target: str | None = None
    cmd: str | list[str] | None = None
    timeout_sec: int | None = None
    collect: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    no_extract: bool = False

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any] | None) -> "ProfileConfig":
        data = data or {}
        timeout = data.get("timeout_sec", data.get("timeout"))
        return cls(
            name=name,
            target=_optional_str(data.get("target")),
            cmd=data.get("cmd", data.get("command")),
            timeout_sec=_optional_int(timeout),
            collect=[str(item) for item in data.get("collect", [])],
            env={str(key): str(value) for key, value in data.get("env", {}).items()},
            no_extract=bool(data.get("no_extract", False)),
        )


@dataclass
class RemoteRunConfig:
    targets: dict[str, TargetConfig] = field(default_factory=dict)
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemoteRunConfig":
        targets = {
            name: TargetConfig.from_dict(name, value)
            for name, value in data.get("targets", {}).items()
        }
        profiles = {
            name: ProfileConfig.from_dict(name, value)
            for name, value in data.get("profiles", {}).items()
        }
        return cls(targets=targets, profiles=profiles)

    @classmethod
    def load(cls, path: str | Path | None) -> "RemoteRunConfig":
        if path is None:
            default_path = Path(".agent-remote/config.json")
            if not default_path.exists():
                return cls()
            path = default_path
        config_path = Path(path).expanduser()
        if not config_path.exists():
            raise FileNotFoundError(f"config file not found: {config_path}")
        if config_path.suffix == ".json":
            return cls.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
        if config_path.suffix == ".toml":
            if tomllib is None:
                raise RuntimeError("TOML config requires Python 3.11 or newer")
            with config_path.open("rb") as handle:
                return cls.from_dict(tomllib.load(handle))
        raise ValueError(f"unsupported config format: {config_path.suffix}")

    def profile(self, name: str | None) -> ProfileConfig | None:
        if name is None:
            return None
        try:
            return self.profiles[name]
        except KeyError as exc:
            raise KeyError(f"profile not found in config: {name}") from exc

    def target(self, name: str | None) -> TargetConfig | None:
        if name is None:
            return None
        return self.targets.get(name)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
