# Work Plan

## Goal

Build a controlled remote execution framework that lets an AI agent on a build
host deploy compiled artifacts to an execution host, trigger execution, and
retrieve logs and results.

The primary mode is relay-first: the build host submits jobs to a relay, and
execution-host workers poll and return results through that same relay. Direct
SSH is only an auxiliary convenience path.

## Phase 1: MVP Relay Runner

Deliver a filesystem relay implementation that works with:

- a local directory for tests
- a shared directory
- an SFTP-mounted directory
- a Windows PC relay directory

Capabilities:

- submit artifact and manifest
- claim jobs by target
- execute command on worker host
- capture stdout, stderr, exit code, timing, and metadata
- collect selected result files
- fetch job results

## Phase 2: Agent-Friendly CLI

Expose stable commands:

- `remote-run submit`
- `remote-run status`
- `remote-run logs`
- `remote-run fetch`
- `remote-run worker`

Auxiliary command:

- `remote-run ssh-submit`

All commands that return machine-readable information should support `--json`.

Status:

- `submit`, `status`, `logs`, `fetch`, and `worker` are implemented.
- `ssh-submit` is implemented for direct SSH mode.
- JSON output is implemented for submit, status, worker, and ssh-submit.
- profile config is implemented for submit and ssh-submit.

## Phase 3: Safety

Add:

- command allowlists
- profile allowlists
- max artifact size
- max log size
- worker concurrency limits
- audit logs

Status:

- worker command allowlists are implemented.
- worker profile allowlists are implemented.
- relay audit logs are implemented.

## Phase 4: Relay Evolution and Auxiliary Direct Transport

Add:

- HTTP relay server as the next relay backend
- direct SSH transport as an auxiliary mode
- resumable upload/download where needed

## Phase 5: Diagnostics

Add:

- failure classification
- concise evidence snippets
- suggestions for missing libraries, failed commands, timeouts, and missing files
