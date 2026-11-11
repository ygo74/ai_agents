# Implementation Plan — direct HTTPS and branch quality gates

## SPEC approval status

The user approved the HTTPS scope and has now explicitly deferred CI changes
until the runtime feature is merged and a compatible version is published.
Work is owned by `ai_agents` on `feature/37-mcp-agent-endpoints`; the runtime
repository and CI workflow remain unchanged. The user has authorized commit
and push after the required local quality gates pass.

## Existing architecture and reuse analysis

- Mail and Wiki keep HTTP server startup in their outer adapters:
  `agents/mail/src/ai_agent_lab/mail/adapters/http/server.py` and
  `agents/wiki/src/ai_agent_lab/wiki/adapters/http/server.py`. Each loads its
  selected environment and calls `uvicorn.run` with a FastAPI factory. These
  adapters are the right place to pass Uvicorn TLS options; domain, bootstrap,
  manifest, and framework code need no change.
- The Docker images already invoke Uvicorn directly with its `--factory` option.
  Uvicorn natively supports `--ssl-certfile` and `--ssl-keyfile`, so the image
  entrypoints need no wrapper or TLS abstraction. Deployment examples will
  override the existing command and mount certificate files read-only.
- Both images use `deploy/healthcheck.py`, which currently checks one HTTP URL.
  Keep this small shared probe and extend it to try the explicitly supplied
  loopback HTTP and HTTPS URLs for Mail and Wiki. The TLS probe may skip
  certificate identity verification only for a loopback URL, since a public
  certificate normally does not name `127.0.0.1`; refuse redirects so that
  exception cannot carry over to another host, and reject credentials in probe
  URLs. External clients retain standard certificate verification. Keep
  MCP-server health checks on their current single HTTP URL.
- There are no existing tests for the two HTTP launchers or the shared
  health-check script. Add focused tests in `tests/unit/` using patched
  environment loading and `uvicorn.run`, plus mocked URL probes. Do not bind a
  port, generate certificates, or read certificate/key contents in these tests.
- Do not introduce a shared TLS settings model, environment configuration, or
  runtime API: the two launchers have a small, identical argument boundary and
  Uvicorn already owns TLS loading and lifecycle.
- `.github/workflows/quality.yml` currently checks out runtime release
  `V0.8.2`, which predates MCP endpoint manifest fields already used by the Mail
  scenario. The runtime feature branch contains the matching contract at
  `98c7fad26cfc8f258d57f85d511de63a22f802d8`. Per the user's direction, leave
  the workflow unchanged until the runtime feature is merged and a compatible
  version is published; record this as a follow-up.
- The real-stdio MCP test times out under the restricted local runner because
  its child process cannot complete the handshake there. The exact focused test
  passes outside that isolation. Do not change application or test code for
  this environment-specific behavior; run subprocess-backed checks in a
  process-capable environment and report the actual result.
- The full run against the compatible runtime source found seven existing JWT
  tests whose fixture environments omit `MAIL_AGENT_HTTP_MCP_RESOURCE_URL` or
  `WIKI_AGENT_HTTP_MCP_RESOURCE_URL`, now required by the runtime manifest
  contract. Add a harmless test URL to those fixtures; do not weaken the runtime
  validation or change agent behavior.

## Repository and component scope

1. Mail and Wiki HTTP adapter launchers: accept optional `--ssl-certfile` and
   `--ssl-keyfile` paths, require the pair together, and pass Uvicorn's
   `ssl_certfile` / `ssl_keyfile` arguments only when both are supplied.
2. Shared `deploy/healthcheck.py` and the Mail/Wiki Docker health checks: probe
   the local HTTP and HTTPS endpoint as applicable, with a bounded total
   execution time and loopback-only TLS verification bypass. Preserve the
   single-URL health check used by the standalone MCP server.
3. Deployment and user guides: show direct HTTPS startup, a read-only mounted
   certificate chain and private key, the published HTTPS port, certificate
   file permissions, and the relationship between the listener and MCP
   `resource_url`.
4. JWT test fixtures in `tests/contract/test_oidc_http_lifecycle.py`,
   `tests/integration/test_mail_environment_selection.py`, and
   `tests/security/test_wiki_http_credential_ownership.py`: provide the
   manifest's configured MCP resource URL when constructing JWT services.
5. No manifest/schema, agent behavior, authentication, MCP protocol, runtime
   source package, CI workflow, dependency, or published artifact changes.

## Ordered steps and dependencies

### A-001 — Add failing launcher and probe tests

- Add tests proving each launcher passes no TLS kwargs in its existing HTTP
  mode, passes both paths to Uvicorn when configured, and rejects either
  unmatched path before Uvicorn starts.
- Add health-check tests for one URL (existing MCP-server use), multiple
  candidate URLs (HTTP and HTTPS agent use), and HTTPS verification behavior:
  bypass only for loopback probes, preserve normal verification for a
  non-loopback HTTPS URL, refuse redirects, and reject credentials in URLs.
- Completion: focused new tests fail against current code for the missing
  behavior and require no real listener or certificate.
- Depends on: approved SPEC.

### A-002 — Implement the launcher TLS options

- Add the paired `--ssl-certfile` and `--ssl-keyfile` arguments to each
  repository-owned HTTP launcher.
- Reject an incomplete pair with a clear argparse error before loading the
  application or starting Uvicorn.
- Forward both file paths to Uvicorn only when configured; preserve all current
  defaults and behavior otherwise.
- Completion: launcher tests from A-001 pass; Uvicorn remains the only TLS
  implementation and certificate loader.
- Depends on: A-001.

### A-003 — Make image liveness checks protocol-aware

- Extend the health-check command to try candidate URLs and succeed when the
  local service responds with an existing accepted status. Bound each probe so
  the total remains below the images' six-second Docker health-check timeout.
- For HTTPS candidates, disable certificate identity verification only when
  the target host is a loopback address. Continue to use normal verification
  for any non-loopback HTTPS target; never include credentials or follow
  redirects to another URL.
- Update Mail and Wiki image health-check commands to supply both HTTP and
  HTTPS loopback URLs on their existing ports. Keep the standalone MCP-server
  image's HTTP-only command unchanged.
- Completion: focused health-check tests pass and both container modes have a
  local liveness probe within the configured timeout.
- Depends on: A-001.

### A-004 — Document direct TLS configuration

- Update the Mail and Wiki HTTP guides with the launcher flags, pair
  requirement, HTTPS request URLs, and the distinction between MCP
  `resource_url` metadata and listener TLS.
- Update `doc/users/deployment.md` and `deploy/README.md` with a Docker example
  that mounts a certificate chain and private key read-only, passes Uvicorn's
  native TLS flags through the container command, and maps a public HTTPS port
  to the agent's TLS listener. State that keys must be readable by the
  non-root container user but must not be baked into the image or repository.
- Completion: a developer can follow the local launcher and container
  documentation without adding a reverse proxy or changing the runtime
  manifest to activate TLS.
- Depends on: A-002 and A-003.

### A-005 — Defer CI runtime alignment

- Leave `.github/workflows/quality.yml` unchanged as requested. Record that its
  runtime `V0.8.2` checkout predates the Mail manifest contract on this branch.
- Revisit CI after the runtime feature is merged and a compatible version is
  published.
- Completion: the deferred CI follow-up and its prerequisite are recorded.
- Depends on: user direction; no implementation change in this task.

### A-006 — Complete MCP resource URL test configuration

- Update the affected Mail and Wiki JWT test fixtures to set the MCP resource
  URL referenced by their manifests. Keep it fixture-local, with no real
  network access.
- Completion: the seven full-suite failures caused by a missing required
  environment reference pass against the compatible runtime source.
- Depends on: user authorization to resolve MCP blockers.

### A-007 — Run repository checks and review the change

- Run focused HTTPS tests, then Ruff, mypy, and the complete pytest suite using
  the compatible runtime feature source already available in the development
  environment. Include the Mail manifest scenario and real stdio transport
  tests.
- Run stdio-backed tests in a process-capable environment; the same focused
  test already passed outside local process isolation.
- Review that private key contents never enter logs, configuration values, or
  test output; that the TLS verification exception is limited to loopback
  liveness probes; and that HTTP behavior is unchanged without the flags.
- Record actual commands and results in `JOURNAL.md`.
- Depends on: A-002, A-003, A-004, and A-006.

## Test-first validation

Start with the focused failing launcher and health-check tests, implement only
the behavior needed to make them pass, then run the regression checks. The
tests use patched dependencies and URL opener responses rather than live
services. No test needs an identity provider or model provider. The MCP stdio
regression uses the repository's local reference-server subprocess and does not
open a network listener.

The repository CI quality gates are:

- `python -m ruff check .`
- `python -m mypy`
- `python -m pytest --junitxml=test-results.xml`

Also run the focused test files directly before the full suite. Report only
checks that actually complete and pass.

The local gate uses the runtime feature source because the published `V0.8.2`
package predates this branch's Mail MCP endpoint manifest fields. The CI workflow
will remain unchanged until the user-requested runtime merge and release.

## Security and deployment impact

- TLS protects traffic between clients and Uvicorn; the existing API-key/JWT
  authentication and agent authorization remain mandatory and unchanged.
- Pass certificate paths, never certificate or private-key contents. For
  containers, mount files read-only from a secret or protected host directory;
  confirm the non-root UID can read them. Do not add the files to Docker build
  context or commit them.
- TLS verification bypass is permitted only for the local liveness probe to an
  IP loopback address or `localhost`. The probe does not follow redirects, so
  the exception cannot be used for another host. The general-purpose HTTPS path
  and all external clients verify server identity normally.
- Operators own certificate validity, hostname coverage, permissions, renewal,
  and expiry monitoring. The agent continues to fail startup through Uvicorn
  if a supplied certificate cannot be loaded.
- Binding HTTPS on the existing container port means the published endpoint
  and health URL use HTTPS; clients must use the configured HTTPS scheme. Mail's
  JWT-protected MCP metadata must continue to advertise the externally reachable
  `/mcp` URL.

## Performance and compatibility

- No application request processing, retained state, or database behavior
  changes. There is no new in-process service or state owner.
- TLS adds Uvicorn/OpenSSL handshake work and certificate loading, but this
  change introduces no custom cryptographic path. No independent latency,
  throughput, or memory target is defined; no performance benchmark is needed
  for the listener configuration alone.
- Startup readiness remains observable through Docker health checks. The
  health-check script's sequential probe time is bounded below the configured
  Docker timeout.
- HTTP remains the default when certificate options are omitted. No runtime
  source, dependency, runtime manifest, or language-parity change is required.
- CI still references runtime `V0.8.2`, which predates this branch's endpoint
  manifest contract. It remains unchanged by user direction; align it with a
  published runtime version after the runtime feature is merged and released.

## Documentation and examples

Update only the user and deployment pages in A-004. Keep request tracking under
`spec/implementation/`; do not consolidate the repository specification or
update unrelated contributor documentation as part of this request.

## Risks and completion criteria

- A mounted private key may not be readable by the image's non-root user; the
  deployment example must state the permission requirement without weakening
  the container user.
- Loopback HTTPS health checks intentionally validate reachability and TLS
  handshake, not public certificate identity. External validation remains the
  responsibility of clients and deployment checks.
- Finish when launcher, health-check, and repository checks pass; the guides
  explain direct HTTPS operation; HTTP defaults and MCP server health checks
  remain compatible; and actual validation is recorded in the request journal.
