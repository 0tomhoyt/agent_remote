from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from secrets import token_hex
from typing import Any


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELED = "CANCELED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_job_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"job-{stamp}-{token_hex(4)}"


@dataclass
class ArtifactRef:
    name: str
    sha256: str
    stored_name: str
    size_bytes: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRef":
        return cls(
            name=str(data["name"]),
            sha256=str(data["sha256"]),
            stored_name=str(data["stored_name"]),
            size_bytes=int(data.get("size_bytes", 0)),
        )


@dataclass
class DeploySpec:
    clean_before_run: bool = True
    extract: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DeploySpec":
        data = data or {}
        return cls(
            clean_before_run=bool(data.get("clean_before_run", True)),
            extract=bool(data.get("extract", True)),
        )


@dataclass
class CommandSpec:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    timeout_sec: int = 600

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandSpec":
        return cls(
            argv=[str(part) for part in data["argv"]],
            env={str(key): str(value) for key, value in data.get("env", {}).items()},
            timeout_sec=int(data.get("timeout_sec", 600)),
        )


@dataclass
class JobManifest:
    job_id: str
    target: str
    artifact: ArtifactRef
    command: CommandSpec
    deploy: DeploySpec = field(default_factory=DeploySpec)
    collect: list[str] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(default_factory=utc_now)
    runner_id: str | None = None
    exit_code: int | None = None
    timestamps: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobManifest":
        return cls(
            job_id=str(data["job_id"]),
            target=str(data["target"]),
            artifact=ArtifactRef.from_dict(data["artifact"]),
            command=CommandSpec.from_dict(data["command"]),
            deploy=DeploySpec.from_dict(data.get("deploy")),
            collect=[str(item) for item in data.get("collect", [])],
            status=JobStatus(str(data.get("status", JobStatus.PENDING.value))),
            created_at=str(data.get("created_at", utc_now())),
            runner_id=data.get("runner_id"),
            exit_code=data.get("exit_code"),
            timestamps={str(key): str(value) for key, value in data.get("timestamps", {}).items()},
            error=data.get("error"),
        )
