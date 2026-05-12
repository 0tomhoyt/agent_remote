from __future__ import annotations

import shutil
from pathlib import Path

from .models import JobManifest, JobStatus, utc_now
from .util import append_jsonl, atomic_write_json, copy_file_atomic, copytree_replace, read_json


STATUS_DIRS = {
    JobStatus.PENDING: "pending",
    JobStatus.RUNNING: "running",
    JobStatus.SUCCEEDED: "done",
    JobStatus.FAILED: "failed",
    JobStatus.TIMEOUT: "timeout",
    JobStatus.CANCELED: "canceled",
}


class RelayStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.artifacts_dir = self.root / "artifacts"
        self.jobs_dir = self.root / "jobs"
        self.results_dir = self.root / "results"
        self.ensure_layout()

    def ensure_layout(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "audit").mkdir(parents=True, exist_ok=True)
        for dirname in STATUS_DIRS.values():
            (self.jobs_dir / dirname).mkdir(parents=True, exist_ok=True)

    def artifact_path(self, manifest: JobManifest) -> Path:
        return self.artifacts_dir / manifest.artifact.stored_name

    def job_path(self, status: JobStatus, job_id: str) -> Path:
        return self.jobs_dir / STATUS_DIRS[status] / f"{job_id}.json"

    def submit(self, manifest: JobManifest, artifact_path: Path) -> None:
        artifact_dst = self.artifact_path(manifest)
        if not artifact_dst.exists():
            copy_file_atomic(artifact_path, artifact_dst)
        self.submit_manifest(manifest)

    def submit_manifest(self, manifest: JobManifest) -> None:
        artifact_dst = self.artifact_path(manifest)
        if not artifact_dst.exists():
            raise FileNotFoundError(f"artifact not found in relay store: {artifact_dst}")
        manifest.status = JobStatus.PENDING
        manifest.timestamps["submitted_at"] = utc_now()
        atomic_write_json(self.job_path(JobStatus.PENDING, manifest.job_id), manifest.to_dict())
        self.audit("job_submitted", manifest)

    def find_job_path(self, job_id: str) -> Path | None:
        for status in JobStatus:
            path = self.job_path(status, job_id)
            if path.exists():
                return path
        return None

    def read_manifest(self, job_id: str) -> JobManifest:
        path = self.find_job_path(job_id)
        if path is None:
            raise FileNotFoundError(f"job not found: {job_id}")
        return JobManifest.from_dict(read_json(path))

    def claim_next(self, target: str, runner_id: str) -> JobManifest | None:
        pending_dir = self.jobs_dir / STATUS_DIRS[JobStatus.PENDING]
        running_dir = self.jobs_dir / STATUS_DIRS[JobStatus.RUNNING]
        for path in sorted(pending_dir.glob("*.json")):
            manifest = JobManifest.from_dict(read_json(path))
            if manifest.target != target:
                continue
            claimed_path = running_dir / path.name
            try:
                path.rename(claimed_path)
            except FileNotFoundError:
                continue
            manifest.status = JobStatus.RUNNING
            manifest.runner_id = runner_id
            manifest.timestamps["started_at"] = utc_now()
            atomic_write_json(claimed_path, manifest.to_dict())
            self.audit("job_claimed", manifest)
            return manifest
        return None

    def finish(self, manifest: JobManifest, result_dir: Path, status: JobStatus) -> None:
        manifest.status = status
        manifest.timestamps["finished_at"] = utc_now()
        relay_result_dir = self.results_dir / manifest.job_id
        copytree_replace(result_dir, relay_result_dir)
        self.finish_uploaded_results(manifest, status)

    def finish_uploaded_results(self, manifest: JobManifest, status: JobStatus) -> None:
        relay_result_dir = self.results_dir / manifest.job_id
        if not relay_result_dir.exists():
            raise FileNotFoundError(f"result directory not found: {relay_result_dir}")
        manifest.status = status
        manifest.timestamps["finished_at"] = manifest.timestamps.get("finished_at", utc_now())
        final_path = self.job_path(status, manifest.job_id)
        atomic_write_json(final_path, manifest.to_dict())
        running_path = self.job_path(JobStatus.RUNNING, manifest.job_id)
        running_path.unlink(missing_ok=True)
        self.audit("job_finished", manifest)

    def result_path(self, job_id: str) -> Path:
        return self.results_dir / job_id

    def read_log(self, job_id: str, name: str) -> str:
        path = self.result_path(job_id) / name
        if not path.exists():
            raise FileNotFoundError(f"log not found for {job_id}: {name}")
        return path.read_text(encoding="utf-8", errors="replace")

    def fetch_results(self, job_id: str, out_dir: Path) -> None:
        src = self.result_path(job_id)
        if not src.exists():
            raise FileNotFoundError(f"results not found for {job_id}")
        out_dir = out_dir.expanduser().resolve()
        if out_dir.exists():
            shutil.rmtree(out_dir)
        shutil.copytree(src, out_dir)

    def audit(self, event: str, manifest: JobManifest) -> None:
        append_jsonl(
            self.root / "audit" / "events.jsonl",
            {
                "event": event,
                "time": utc_now(),
                "job_id": manifest.job_id,
                "target": manifest.target,
                "status": manifest.status.value,
                "profile": manifest.profile,
                "runner_id": manifest.runner_id,
                "exit_code": manifest.exit_code,
                "error": manifest.error,
            },
        )
