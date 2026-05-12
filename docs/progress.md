# Progress

## 2026-05-12

Status: relay-first documentation updated and pushed

Repository:

- Local repository initialized at `/Users/tomhoyt/Desktop/terminal_trans`.
- Remote origin configured as `https://github.com/0tomhoyt/agent_remote.git`.
- Git global proxy settings were removed at the user's request.
- Remote repository fetched successfully and appeared empty at project start.
- Initial implementation commit: `c072be7`.
- `main` pushed to `origin`.
- Second implementation commit: `1bb603a`.
- Safety follow-up commit: `16187f0`.
- README usage guide commit: `916b508`.
- Relay-first documentation commit: `3b48efc`.

Completed:

- Created initial project structure.
- Added README and package metadata.
- Implemented the MVP relay runner code path:
  - manifest model
  - filesystem relay
  - execution worker
  - CLI commands
- Added Windows relay layout notes.
- Added unit/integration tests for success and timeout jobs.
- Added CLI end-to-end test for submit, worker, status, logs, and fetch.
- Ran validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests`
  - `python3 -m compileall src tests`
- Implemented second slice:
  - profile-based submit config via JSON/TOML
  - target-level worker command allowlists
  - `ssh-submit` direct SSH mode
  - example config at `examples/remote-run.config.json`
- Implemented safety follow-up:
  - target-level worker profile allowlists
  - relay audit log at `audit/events.jsonl`
- Added tests for:
  - profile submit config
  - disallowed command rejection
  - disallowed profile rejection
  - relay audit events
  - SSH direct transport command flow
- Ran second-slice validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests`
  - `python3 -m compileall src tests`
  - `PYTHONPATH=src python3 -m agent_remote.cli --help`
  - `PYTHONPATH=src python3 -m agent_remote.cli ssh-submit --help`
- Ran safety follow-up validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests`
  - `python3 -m compileall src tests`
- Expanded README into a detailed Chinese usage guide covering installation,
  CLI rules, relay layout, local demo, Windows relay, profile config, worker
  safety limits, SSH direct mode, artifacts, collect patterns, JSON output,
  audit logs, and troubleshooting.
- Ran README command validation:
  - `PYTHONPATH=src python3 -m agent_remote.cli --help`
  - `PYTHONPATH=src python3 -m agent_remote.cli ssh-submit --help`
- Updated README and work plan wording to make relay mode the primary/default
  architecture and SSH direct an auxiliary convenience path.
- Added a relay-first command quick reference that highlights submit, worker,
  status, logs, and fetch as the daily workflow.
- Ran relay-first documentation command validation:
  - `PYTHONPATH=src python3 -m agent_remote.cli --help`
  - `PYTHONPATH=src python3 -m agent_remote.cli worker --help`

In progress:

- Planning the HTTP relay service skeleton.

Next:

- Add HTTP relay design and service skeleton.
- Improve SSH direct mode bootstrap docs for installing `agent_remote` on the execution host.
