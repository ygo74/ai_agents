# Implementation Tasks

- [x] A-001 — Add failing Mail/Wiki launcher and health-check tests in
  `tests/unit/`; cover HTTP defaults, TLS option forwarding, incomplete pairs,
  one and multiple probe URLs, and loopback-only TLS verification bypass.
  Completion: tests fail for the expected missing behavior without binding a
  port or accessing certificate files. Depends on: approved PLAN.
- [x] A-002 — Add paired `--ssl-certfile` and `--ssl-keyfile` options to the
  Mail and Wiki HTTP launchers and forward them to Uvicorn when both are set.
  Completion: A-001 launcher tests pass and current HTTP launch defaults remain
  unchanged. Depends on: A-001.
- [x] A-003 — Extend `deploy/healthcheck.py` to accept candidate URLs and probe
  HTTPS without certificate identity verification only for loopback URLs, and
  reject credentials and redirects; update Mail/Wiki image health checks to supply HTTP and
  HTTPS candidates.
  Completion: focused health-check tests pass within the six-second Docker
  timeout and the MCP server health check still uses its existing HTTP URL.
  Depends on: A-001.
- [x] A-004 — Document direct HTTPS startup and read-only certificate/key
  mounts in Mail/Wiki HTTP guides, `doc/users/deployment.md`, and
  `deploy/README.md`. Completion: an operator can configure the service without
  a reverse proxy, understands that `resource_url` does not enable TLS, and is
  told how to protect mounted key files. Depends on: A-002, A-003.
- [x] A-005 — Defer CI runtime alignment as requested. Keep the workflow on
  `V0.8.2` until the runtime feature is merged and a compatible version is
  published; record this follow-up in the SPEC and PLAN.
- [x] A-006 — Set the manifest-referenced Mail or Wiki MCP resource URL in the
  affected JWT test fixtures. Completion: the 7 fixture failures against the
  compatible runtime source pass without changing production behavior. Depends
  on: the runtime contract used by this branch.
- [x] A-007 — Run focused HTTPS tests, Ruff, mypy, and the full pytest suite
  against the compatible runtime source in the development environment; review
  TLS safety and compatibility, then record actual results in `JOURNAL.md`. Run
  stdio-backed tests in a process-capable environment. Completion: all required
  local checks pass and their results are recorded. Depends on: A-002, A-003,
  A-004, and A-006.
