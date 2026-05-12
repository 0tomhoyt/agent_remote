from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

from .config import DEFAULT_RELAY_ROOT, DEFAULT_TIMEOUT_SEC, DEFAULT_WORK_ROOT, RemoteRunConfig
from .models import CommandSpec, DeploySpec, JobManifest, new_job_id
from .relay import RelayStore
from .runner import Runner
from .ssh_transport import SSHDirectTransport
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
        default=None,
        help="relay directory shared by submitters and workers",
    )
    parser.add_argument("--config", help="optional JSON or TOML config file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit", help="submit an artifact execution job")
    add_submit_args(submit)
    submit.set_defaults(func=cmd_submit)

    ssh_submit = subparsers.add_parser("ssh-submit", help="submit and run a job through SSH direct mode")
    add_submit_args(ssh_submit)
    ssh_submit.add_argument("--ssh-host", help="SSH host, for example user@exec-host")
    ssh_submit.add_argument("--ssh-port", type=int)
    ssh_submit.add_argument("--remote-relay-root", help="relay directory on the execution host")
    ssh_submit.add_argument("--remote-work-root", help="worker directory on the execution host")
    ssh_submit.add_argument("--remote-python", help="remote Python executable")
    ssh_submit.set_defaults(func=cmd_ssh_submit)

    status = subparsers.add_parser("status", help="show job status")
    status.add_argument("job_id")
    status.add_argument("--target", help="target name used to resolve relay_root from config")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    logs = subparsers.add_parser("logs", help="show job stdout or stderr")
    logs.add_argument("job_id")
    logs.add_argument("--target", help="target name used to resolve relay_root from config")
    logs.add_argument("--stderr", action="store_true")
    logs.add_argument("--tail", type=int)
    logs.set_defaults(func=cmd_logs)

    fetch = subparsers.add_parser("fetch", help="fetch job result directory")
    fetch.add_argument("job_id")
    fetch.add_argument("--target", help="target name used to resolve relay_root from config")
    fetch.add_argument("--out", required=True)
    fetch.set_defaults(func=cmd_fetch)

    worker = subparsers.add_parser("worker", help="run an execution worker")
    worker.add_argument("--target", required=True)
    worker.add_argument("--work-root")
    worker.add_argument("--runner-id")
    worker.add_argument("--allow-command", action="append", default=[])
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-interval", type=float, default=2.0)
    worker.add_argument("--json", action="store_true")
    worker.set_defaults(func=cmd_worker)

    return parser


def add_submit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="profile name from config")
    parser.add_argument("--target")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--cmd", help="command to execute inside the unpacked artifact")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--collect", action="append", default=[])
    parser.add_argument("--env", action="append", default=[], help="environment entry in KEY=VALUE form")
    parser.add_argument("--no-extract", action="store_true")
    parser.add_argument("--json", action="store_true")


def cmd_submit(args: argparse.Namespace) -> int:
    config = RemoteRunConfig.load(args.config)
    manifest, artifact_path = build_manifest(args, config)
    relay = RelayStore(resolve_relay_root(args, config, manifest.target))
    relay.submit(manifest, artifact_path)
    print_submit_result(args, manifest)
    return 0


def cmd_ssh_submit(args: argparse.Namespace) -> int:
    config = RemoteRunConfig.load(args.config)
    manifest, artifact_path = build_manifest(args, config)
    target_config = config.target(manifest.target)
    relay = RelayStore(resolve_relay_root(args, config, manifest.target))
    relay.submit(manifest, artifact_path)
    transport = SSHDirectTransport(
        host=args.ssh_host or (target_config.ssh_host if target_config else None) or "",
        port=args.ssh_port if args.ssh_port is not None else (target_config.ssh_port if target_config else None),
        remote_relay_root=args.remote_relay_root
        or (target_config.remote_relay_root if target_config else None)
        or DEFAULT_RELAY_ROOT,
        remote_work_root=args.remote_work_root
        or (target_config.remote_work_root if target_config else None)
        or DEFAULT_WORK_ROOT,
        remote_python=args.remote_python
        or (target_config.remote_python if target_config else None)
        or "python3",
    )
    if not transport.host:
        raise ValueError("--ssh-host is required unless target config defines ssh_host")
    finished = transport.run_job(relay, manifest)
    output = {
        "ok": finished.exit_code == 0,
        "job_id": finished.job_id,
        "target": finished.target,
        "status": finished.status.value,
        "exit_code": finished.exit_code,
        "artifact_sha256": finished.artifact.sha256,
    }
    print_json_or_text(output, args.json, f"{finished.job_id} {finished.status.value}")
    return 0


def build_manifest(args: argparse.Namespace, config: RemoteRunConfig) -> tuple[JobManifest, Path]:
    profile = config.profile(args.profile)
    target = args.target or (profile.target if profile else None)
    if target is None:
        raise ValueError("--target is required unless the selected profile defines target")
    target_config = config.target(target)
    artifact_path = Path(args.artifact).expanduser().resolve()
    if not artifact_path.exists():
        raise FileNotFoundError(f"artifact not found: {artifact_path}")
    ref = artifact_ref(artifact_path)
    env = {}
    if profile:
        env.update(profile.env)
    env.update(parse_env(args.env))
    cmd = args.cmd or (profile.cmd if profile else None)
    if cmd is None:
        raise ValueError("--cmd is required unless the selected profile defines cmd")
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(part) for part in cmd]
    if not argv:
        raise ValueError("--cmd produced an empty argv")
    timeout = (
        args.timeout
        if args.timeout is not None
        else profile.timeout_sec
        if profile and profile.timeout_sec is not None
        else target_config.default_timeout_sec
        if target_config and target_config.default_timeout_sec is not None
        else DEFAULT_TIMEOUT_SEC
    )
    collect: list[str] = []
    if profile:
        collect.extend(profile.collect)
    collect.extend(args.collect)
    manifest = JobManifest(
        job_id=new_job_id(),
        target=target,
        artifact=ref,
        profile=args.profile,
        deploy=DeploySpec(extract=not (args.no_extract or (profile.no_extract if profile else False))),
        command=CommandSpec(argv=argv, env=env, timeout_sec=timeout),
        collect=collect,
    )
    return manifest, artifact_path


def print_submit_result(args: argparse.Namespace, manifest: JobManifest) -> None:
    output = {
        "ok": True,
        "job_id": manifest.job_id,
        "target": manifest.target,
        "status": manifest.status.value,
        "artifact_sha256": manifest.artifact.sha256,
    }
    print_json_or_text(output, args.json, f"submitted {manifest.job_id}")


def cmd_status(args: argparse.Namespace) -> int:
    config = RemoteRunConfig.load(args.config)
    relay = RelayStore(resolve_relay_root(args, config, args.target))
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
    config = RemoteRunConfig.load(args.config)
    relay = RelayStore(resolve_relay_root(args, config, args.target))
    name = "stderr.log" if args.stderr else "stdout.log"
    text = relay.read_log(args.job_id, name)
    print(tail_text(text, args.tail), end="")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    config = RemoteRunConfig.load(args.config)
    relay = RelayStore(resolve_relay_root(args, config, args.target))
    relay.fetch_results(args.job_id, Path(args.out))
    print(f"fetched {args.job_id} -> {Path(args.out).expanduser().resolve()}")
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    config = RemoteRunConfig.load(args.config)
    target_config = config.target(args.target)
    relay = RelayStore(resolve_relay_root(args, config, args.target))
    work_root = args.work_root or (target_config.work_root if target_config else None) or DEFAULT_WORK_ROOT
    allowed_commands: list[str] = []
    if target_config:
        allowed_commands.extend(target_config.allowed_commands)
    allowed_commands.extend(args.allow_command)
    runner = Runner(
        relay=relay,
        target=args.target,
        work_root=work_root,
        runner_id=args.runner_id,
        allowed_commands=allowed_commands,
    )
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


def resolve_relay_root(args: argparse.Namespace, config: RemoteRunConfig, target: str | None) -> str:
    if args.relay_root:
        return args.relay_root
    target_config = config.target(target)
    if target_config and target_config.relay_root:
        return target_config.relay_root
    return DEFAULT_RELAY_ROOT


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
