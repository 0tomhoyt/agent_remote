# Work Plan

## Goal

Build a controlled remote execution framework that lets an AI agent on a build
host deploy compiled artifacts to an execution host, trigger execution, and
retrieve logs and results.

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

All commands that return machine-readable information should support `--json`.

## Phase 3: Safety

Add:

- command allowlists
- profile allowlists
- max artifact size
- max log size
- worker concurrency limits
- audit logs

## Phase 4: Direct and HTTP Transports

Add:

- direct SSH transport
- HTTP relay server
- resumable upload/download where needed

## Phase 5: Diagnostics

Add:

- failure classification
- concise evidence snippets
- suggestions for missing libraries, failed commands, timeouts, and missing files
