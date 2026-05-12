from __future__ import annotations

from pathlib import Path

from .models import JobManifest


def validate_allowed_command(manifest: JobManifest, allowed_commands: list[str] | None) -> None:
    if not allowed_commands:
        return
    if not manifest.command.argv:
        raise PermissionError("empty command is not allowed")
    command = manifest.command.argv[0]
    candidates = {command, Path(command).name}
    if candidates.isdisjoint(set(allowed_commands)):
        allowed = ", ".join(sorted(allowed_commands))
        raise PermissionError(f"command is not allowed: {command}; allowed commands: {allowed}")
