from __future__ import annotations

import json
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .models import JobManifest, JobStatus
from .relay import RelayStore
from .util import (
    extract_tar_safe,
    sha256_file,
    tar_directory,
)


class HTTPRelayError(RuntimeError):
    pass


class HTTPRelayClient:
    def __init__(self, base_url: str, cache_root: str | Path = ".agent-remote/cache"):
        self.base_url = base_url.rstrip("/")
        self.cache_root = Path(cache_root).expanduser().resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def submit(self, manifest: JobManifest, artifact_path: Path) -> None:
        self._put_file(
            f"/artifacts/{urllib.parse.quote(manifest.artifact.stored_name)}",
            artifact_path,
            headers={"X-Artifact-Sha256": manifest.artifact.sha256},
        )
        self._request_json("POST", "/jobs", manifest.to_dict())

    def read_manifest(self, job_id: str) -> JobManifest:
        data = self._request_json("GET", f"/jobs/{urllib.parse.quote(job_id)}")
        return JobManifest.from_dict(data)

    def claim_next(self, target: str, runner_id: str) -> JobManifest | None:
        try:
            data = self._request_json(
                "POST",
                "/jobs/claim",
                {"target": target, "runner_id": runner_id},
                none_on_204=True,
            )
        except HTTPRelayError as exc:
            raise exc
        if data is None:
            return None
        return JobManifest.from_dict(data)

    def artifact_path(self, manifest: JobManifest) -> Path:
        artifact_dir = self.cache_root / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / manifest.artifact.stored_name
        if path.exists() and sha256_file(path) == manifest.artifact.sha256:
            return path
        self._get_file(f"/artifacts/{urllib.parse.quote(manifest.artifact.stored_name)}", path)
        actual = sha256_file(path)
        if actual != manifest.artifact.sha256:
            path.unlink(missing_ok=True)
            raise ValueError(f"artifact sha256 mismatch: expected {manifest.artifact.sha256}, got {actual}")
        return path

    def finish(self, manifest: JobManifest, result_dir: Path, status: JobStatus) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / f"{manifest.job_id}.tar.gz"
            tar_directory(result_dir, archive)
            self._put_file(f"/results/{urllib.parse.quote(manifest.job_id)}.tar.gz", archive)
        manifest.status = status
        self._request_json("POST", f"/jobs/{urllib.parse.quote(manifest.job_id)}/finish", manifest.to_dict())

    def read_log(self, job_id: str, name: str) -> str:
        return self._request_text(
            "GET",
            f"/logs/{urllib.parse.quote(job_id)}/{urllib.parse.quote(name)}",
        )

    def fetch_results(self, job_id: str, out_dir: Path) -> None:
        out_dir = out_dir.expanduser().resolve()
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / f"{job_id}.tar.gz"
            self._get_file(f"/results/{urllib.parse.quote(job_id)}.tar.gz", archive)
            if out_dir.exists():
                shutil.rmtree(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            extract_tar_safe(archive, out_dir)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        none_on_204: bool = False,
    ) -> dict[str, Any] | None:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._url(path),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request) as response:
                if response.status == 204 and none_on_204:
                    return None
                text = response.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 204 and none_on_204:
                return None
            raise HTTPRelayError(self._error_message(exc)) from exc

    def _request_text(self, method: str, path: str) -> str:
        request = urllib.request.Request(self._url(path), method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise HTTPRelayError(self._error_message(exc)) from exc

    def _put_file(self, path: str, src: Path, headers: dict[str, str] | None = None) -> None:
        headers = headers or {}
        headers["Content-Type"] = "application/octet-stream"
        headers["Content-Length"] = str(src.stat().st_size)
        with src.open("rb") as handle:
            request = urllib.request.Request(self._url(path), data=handle, headers=headers, method="PUT")
            try:
                with urllib.request.urlopen(request):
                    return
            except urllib.error.HTTPError as exc:
                raise HTTPRelayError(self._error_message(exc)) from exc

    def _get_file(self, path: str, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(self._url(path), method="GET")
        try:
            with urllib.request.urlopen(request) as response:
                fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
                tmp_path = Path(tmp_name)
                try:
                    with open(fd, "wb", closefd=True) as handle:
                        shutil.copyfileobj(response, handle)
                    tmp_path.replace(dst)
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise
        except urllib.error.HTTPError as exc:
            raise HTTPRelayError(self._error_message(exc)) from exc

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _error_message(exc: urllib.error.HTTPError) -> str:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
            return str(data.get("error", body))
        except json.JSONDecodeError:
            return body or f"HTTP {exc.code}"


def create_http_relay_server(host: str, port: int, relay_root: str | Path) -> ThreadingHTTPServer:
    store = RelayStore(relay_root)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentRemoteHTTPRelay/0.1"

        def do_GET(self) -> None:
            try:
                parsed = urllib.parse.urlparse(self.path)
                parts = _path_parts(parsed.path)
                if parts == ["health"]:
                    self._send_json({"ok": True})
                    return
                if len(parts) == 2 and parts[0] == "jobs":
                    self._send_json(store.read_manifest(_safe_name(parts[1])).to_dict())
                    return
                if len(parts) == 2 and parts[0] == "artifacts":
                    self._send_file(store.artifacts_dir / _safe_name(parts[1]))
                    return
                if len(parts) == 3 and parts[0] == "logs":
                    self._send_text(store.read_log(_safe_name(parts[1]), _safe_name(parts[2])))
                    return
                if len(parts) == 2 and parts[0] == "results" and parts[1].endswith(".tar.gz"):
                    job_id = _safe_name(parts[1][:-7])
                    result_dir = store.result_path(job_id)
                    if not result_dir.exists():
                        raise FileNotFoundError(f"results not found for {job_id}")
                    with tempfile.TemporaryDirectory() as tmp:
                        archive = Path(tmp) / f"{job_id}.tar.gz"
                        tar_directory(result_dir, archive)
                        self._send_file(archive)
                    return
                self._send_error(404, "not found")
            except Exception as exc:
                self._send_exception(exc)

        def do_POST(self) -> None:
            try:
                parsed = urllib.parse.urlparse(self.path)
                parts = _path_parts(parsed.path)
                if parts == ["jobs"]:
                    manifest = JobManifest.from_dict(self._read_json())
                    store.submit_manifest(manifest)
                    self._send_json({"ok": True, "job_id": manifest.job_id})
                    return
                if parts == ["jobs", "claim"]:
                    data = self._read_json()
                    manifest = store.claim_next(str(data["target"]), str(data["runner_id"]))
                    if manifest is None:
                        self.send_response(204)
                        self.end_headers()
                        return
                    self._send_json(manifest.to_dict())
                    return
                if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "finish":
                    manifest = JobManifest.from_dict(self._read_json())
                    if manifest.job_id != _safe_name(parts[1]):
                        raise ValueError("finish job_id does not match URL")
                    store.finish_uploaded_results(manifest, manifest.status)
                    self._send_json({"ok": True, "job_id": manifest.job_id, "status": manifest.status.value})
                    return
                self._send_error(404, "not found")
            except Exception as exc:
                self._send_exception(exc)

        def do_PUT(self) -> None:
            try:
                parsed = urllib.parse.urlparse(self.path)
                parts = _path_parts(parsed.path)
                if len(parts) == 2 and parts[0] == "artifacts":
                    dst = store.artifacts_dir / _safe_name(parts[1])
                    self._read_body_to_file(dst)
                    expected = self.headers.get("X-Artifact-Sha256")
                    if expected and sha256_file(dst) != expected:
                        dst.unlink(missing_ok=True)
                        raise ValueError("artifact sha256 mismatch")
                    self._send_json({"ok": True})
                    return
                if len(parts) == 2 and parts[0] == "results" and parts[1].endswith(".tar.gz"):
                    job_id = _safe_name(parts[1][:-7])
                    with tempfile.TemporaryDirectory() as tmp:
                        archive = Path(tmp) / parts[1]
                        self._read_body_to_file(archive)
                        extract_dir = Path(tmp) / "results"
                        extract_tar_safe(archive, extract_dir)
                        dst = store.result_path(job_id)
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.copytree(extract_dir, dst)
                    self._send_json({"ok": True, "job_id": job_id})
                    return
                self._send_error(404, "not found")
            except Exception as exc:
                self._send_exception(exc)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _read_body_to_file(self, dst: Path) -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            length = int(self.headers.get("Content-Length", "0"))
            fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
            tmp_path = Path(tmp_name)
            try:
                with open(fd, "wb", closefd=True) as handle:
                    remaining = length
                    while remaining > 0:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        handle.write(chunk)
                        remaining -= len(chunk)
                if remaining != 0:
                    raise ValueError("incomplete request body")
                tmp_path.replace(dst)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise

        def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text: str, status: int = 200) -> None:
            body = text.encode("utf-8", errors="replace")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            if not path.exists():
                raise FileNotFoundError(str(path))
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile)

        def _send_error(self, status: int, message: str) -> None:
            self._send_json({"ok": False, "error": message}, status=status)

        def _send_exception(self, exc: Exception) -> None:
            if isinstance(exc, FileNotFoundError):
                self._send_error(404, str(exc))
            elif isinstance(exc, (PermissionError, ValueError, KeyError)):
                self._send_error(400, str(exc))
            else:
                self._send_error(500, f"{type(exc).__name__}: {exc}")

    return ThreadingHTTPServer((host, port), Handler)


def _path_parts(path: str) -> list[str]:
    return [
        urllib.parse.unquote(part)
        for part in path.strip("/").split("/")
        if part
    ]


def _safe_name(name: str) -> str:
    clean = Path(name).name
    if clean != name or not clean:
        raise ValueError(f"unsafe path name: {name}")
    return clean
