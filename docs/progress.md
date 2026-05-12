# Progress

## 2026-05-12

Status: second slice implemented locally

Repository:

- Local repository initialized at `/Users/tomhoyt/Desktop/terminal_trans`.
- Remote origin configured as `https://github.com/0tomhoyt/agent_remote.git`.
- Git global proxy settings were removed at the user's request.
- Remote repository fetched successfully and appeared empty at project start.
- Initial implementation commit: `c072be7`.
- `main` pushed to `origin`.

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
- Added tests for:
  - profile submit config
  - disallowed command rejection
  - SSH direct transport command flow
- Ran second-slice validation:
  - `PYTHONPATH=src python3 -m unittest discover -s tests`
  - `python3 -m compileall src tests`
  - `PYTHONPATH=src python3 -m agent_remote.cli --help`
  - `PYTHONPATH=src python3 -m agent_remote.cli ssh-submit --help`

In progress:

- Preparing the second-slice commit.

Next:

- Add HTTP relay design and service skeleton.
- Add profile allowlists and audit logs.
- Improve SSH direct mode bootstrap docs for installing `agent_remote` on the execution host.
