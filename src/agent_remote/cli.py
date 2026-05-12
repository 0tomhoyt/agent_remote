from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

from .models import CommandSpec, DeploySpec, JobManifest, new_job_id
from .relay import RelayStore
from .runner import Runner
from .util import artifact_ref, tail_text


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 1
    except Exception as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remote-run")
    parser.add_argument(
        "--relay-root",
        default=".agent-remote/relay",
        help="relay directory shared by submitters and workers",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit", help="submit an artifact execution job")
    submit.add_argument("--target", required=True)
    submit.add_argument("--artifact", required=True)
    submit.add_argument("--cmd", required=True, help="command to execute inside the unpacked artifact")
    submit.add_argument("--timeout", type=int, default=600)
    submit.add_argument("--collect", action="append", default=[])
    submit.add_argument("--env", action="append", default=[], help="environment entry in KEY=VALUE form")
    submit.add_argument("--no-extract", action="store_true")
    submit.add_argument("--json", action="store_true")
    submit.set_defaults(func=cmd_submit)

    status = subparsers.add_parser("status", help="show job status")
    status.add_argument("job_id")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    logs = subparsers.add_parser("logs", help="show job stdout or stderr")
    logs.add_argument("job_id")
    logs.add_argument("--stderr", action="store_true")
    logs.add_argument("--tail", type=int)
    logs.set_defaults(func=cmd_logs)

    fetch = subparsers.add_parser("fetch", help="fetch job result directory")
    fetch.add_argument("job_id")
    fetch.add_argument("--out", required=True)
    fetch.set_defaults(func=cmd_fetch)

    worker = subparsers.add_parser("worker", help="run an execution worker")
    worker.add_argument("--target", required=True)
    worker.add_argument("--work-root", default=".agent-remote/worker")
    worker.add_argument("--runner-id")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-interval", type=float, default=2.0)
    worker.add_argument("--json", action="store_true")
    worker.set_defaults(func=cmd_worker)

    return parser


def cmd_submit(args: argparse.Namespace) -> int:
    relay = RelayStore(args.relay_root)
    artifact_path = Path(args.artifact).expanduser().resolve()
    if not artifact_path.exists():
        raise FileNotFoundError(f"artifact not found: {artifact_path}")
    ref = artifact_ref(artifact_path)
    env = parse_env(args.env)
    argv = shlex.split(args.cmd)
    if not argv:
        raise ValueError("--cmd produced an empty argv")
    manifest = JobManifest(
        job_id=new_job_id(),
        target=args.target,
        artifact=ref,
        deploy=DeploySpec(extract=not args.no_extract),
        command=CommandSpec(argv=argv, env=env, timeout_sec=args.timeout),
        collect=list(args.collect),
    )
    relay.submit(manifest, artifact_path)
    output = {
        "ok": True,
        "job_id": manifest.job_id,
        "target": manifest.target,
        "status": manifest.status.value,
        "artifact_sha256": manifest.artifact.sha256,
    }
    print_json_or_text(output, args.json, f"submitted {manifest.job_id}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    relay = RelayStore(args.relay_root)
    manifest = relay.read_manifest(args.job_id)
    if args.json:
        print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))
    else:
        exit_code = "" if manifest.exit_code is None else f" exit_code={manifest.exit_code}"
        print(f"{manifest.job_id} {manifest.status.value}{exit_code}")
        if manifest.error:
            print(f"error: {manifest.error}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    relay = RelayStore(args.relay_root)
    name = "stderr.log" if args.stderr else "stdout.log"
    text = relay.read_log(args.job_id, name)
    print(tail_text(text, args.tail), end="")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    relay = RelayStore(args.relay_root)
    relay.fetch_results(args.job_id, Path(args.out))
    print(f"fetched {args.job_id} -> {Path(args.out).expanduser().resolve()}")
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    relay = RelayStore(args.relay_root)
    runner = Runner(relay=relay, target=args.target, work_root=args.work_root, runner_id=args.runner_id)
    if args.once:
        job_id = runner.run_once()
        output = {"ok": True, "job_id": job_id}
        print_json_or_text(output, args.json, f"ran {job_id}" if job_id else "no job")
        return 0

    while True:
        job_id = runner.run_once()
        if job_id:
            print(f"ran {job_id}", flush=True)
        time.sleep(args.poll_interval)


def parse_env(values: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for entry in values:
        if "=" not in entry:
            raise ValueError(f"invalid --env entry, expected KEY=VALUE: {entry}")
        key, value = entry.split("=", 1)
        if not key:
            raise ValueError("invalid --env entry with empty key")
        env[key] = value
    return env


def print_json_or_text(data: dict[str, object], as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
