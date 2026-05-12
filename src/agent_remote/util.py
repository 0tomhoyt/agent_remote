from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .models import ArtifactRef


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_filename(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return clean or "artifact"


def artifact_ref(path: Path) -> ArtifactRef:
    path = path.resolve()
    digest = sha256_file(path)
    name = path.name
    stored_name = f"{digest}-{sanitize_filename(name)}"
    return ArtifactRef(
        name=name,
        sha256=digest,
        stored_name=stored_name,
        size_bytes=path.stat().st_size,
    )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def copy_file_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
    tmp_path = Path(tmp_name)
    os.close(fd)
    try:
        shutil.copy2(src, tmp_path)
        tmp_path.replace(dst)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def copytree_replace(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def tail_text(text: str, line_count: int | None) -> str:
    if line_count is None or line_count <= 0:
        return text
    lines = text.splitlines()
    return "\n".join(lines[-line_count:]) + ("\n" if lines else "")
