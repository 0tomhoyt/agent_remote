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

Planned next:

- SSH direct transport.
- HTTP relay service.
- command/profile allowlists.
- stronger diagnostics.
- multi-worker locking and heartbeats.
