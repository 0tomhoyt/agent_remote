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


def validate_allowed_profile(manifest: JobManifest, allowed_profiles: list[str] | None) -> None:
    if not allowed_profiles:
        return
    if manifest.profile is None:
        raise PermissionError("ad-hoc jobs are not allowed by this runner")
    if manifest.profile not in set(allowed_profiles):
        allowed = ", ".join(sorted(allowed_profiles))
        raise PermissionError(f"profile is not allowed: {manifest.profile}; allowed profiles: {allowed}")
