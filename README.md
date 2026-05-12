# agent-remote

`agent-remote` is a small remote job runner for AI-assisted development
workflows where code is built on one Linux host and executed/debugged on another.

The first implementation focuses on a filesystem relay. This relay can be a
shared directory, an SFTP-mounted directory, or a directory hosted on a Windows
PC that both Linux machines can access.

## Core Workflow

```text
build host
  remote-run submit --artifact op_package.tar.gz --target exec-a --cmd "./run_case.sh case_001"

relay directory
  artifacts/
  jobs/pending/
  jobs/running/
  jobs/done/
  jobs/failed/
  jobs/timeout/
  results/

execution host
  remote-run worker --target exec-a
```

## Quick Start

Create a relay directory:

```bash
mkdir -p .agent-remote/relay
```

Submit a job:

```bash
python -m agent_remote.cli submit \
  --relay-root .agent-remote/relay \
  --target exec-a \
  --artifact ./dist/op_package.tar.gz \
  --cmd "./run_case.sh case_001" \
  --collect "*.log" \
  --collect "result.json"
```

Run a worker once on the execution host:

```bash
python -m agent_remote.cli worker \
  --relay-root .agent-remote/relay \
  --target exec-a \
  --work-root .agent-remote/worker \
  --once
```

Check status:

```bash
python -m agent_remote.cli status \
  --relay-root .agent-remote/relay \
  <job_id>
```

Fetch results:

```bash
python -m agent_remote.cli fetch \
  --relay-root .agent-remote/relay \
  <job_id> \
  --out ./results/<job_id>
```

## Profile Config

Profiles keep AI agents from repeating long commands and make common runs more
auditable. See `examples/remote-run.config.json`.

```json
{
  "targets": {
    "exec-a": {
      "relay_root": ".agent-remote/relay",
      "work_root": ".agent-remote/worker",
      "default_timeout_sec": 600,
      "allowed_commands": ["sh", "python3", "./run_case.sh"]
    }
  },
  "profiles": {
    "op-test": {
      "target": "exec-a",
      "cmd": "sh run_case.sh case_001",
      "collect": ["*.log", "result.json"],
      "env": {
        "LD_LIBRARY_PATH": "./lib"
      }
    }
  }
}
```

Submit with a profile:

```bash
python -m agent_remote.cli --config examples/remote-run.config.json submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz
```

Run a worker with target-level command allowlists:

```bash
python -m agent_remote.cli --config examples/remote-run.config.json worker \
  --target exec-a \
  --once
```

Query through the target config:

```bash
python -m agent_remote.cli --config examples/remote-run.config.json status \
  <job_id> \
  --target exec-a
```

## SSH Direct Mode

When the build host can SSH to the execution host, `ssh-submit` copies the local
relay job to the remote relay, runs one remote worker pass, and copies results
back to the local relay.

The execution host must have `agent_remote` importable by the configured remote
Python.

```bash
python -m agent_remote.cli --config examples/remote-run.config.json ssh-submit \
  --profile op-test \
  --artifact ./dist/op_package.tar.gz
```

Equivalent command without config:

```bash
python -m agent_remote.cli ssh-submit \
  --target exec-a \
  --artifact ./dist/op_package.tar.gz \
  --cmd "sh run_case.sh case_001" \
  --ssh-host user@exec-a \
  --remote-relay-root /data/agent-remote/relay \
  --remote-work-root /data/agent-remote/worker
```

## Current Scope

Implemented in the MVP:

- Content-addressed artifact upload with SHA-256 verification.
- Atomic job manifest writes.
- Filesystem relay queue.
- Worker-side artifact extraction.
- Command execution with timeout.
- stdout/stderr capture.
- result metadata capture.
- file collection by glob pattern.
- JSON-friendly CLI output.
- Profile-based submit config.
- Worker command allowlists.
- SSH direct mode that reuses the relay worker path.

Planned next:

- HTTP relay service.
- stronger diagnostics.
- multi-worker locking and heartbeats.
