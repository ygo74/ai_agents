# Journal — direct HTTPS for agent HTTP hosts

## Scope and repositories

- Primary repository: `ai_agents` (`/data/repos/ai_agents`).
- Runtime repository: secondary dependency only; no runtime source change is
  currently planned. The CI workflow needs a runtime revision that supports
  this branch's MCP endpoint manifests.
- Working branch at start: `feature/37-mcp-agent-endpoints`.
- No Issue or pull request was requested for this ad hoc change. The user later
  explicitly requested a commit and push and authorized resolving the MCP and
  CI blockers, then asked to defer workflow changes until the runtime feature
  is merged and a compatible version is published. Commit and push are
  authorized after required local checks.

## Progress

- 2026-11-11: Inspected Mail and Wiki Uvicorn launchers, Docker image startup and
  health checks, user deployment documentation, repository quality gates, and
  the current system specification.
- 2026-11-11: Created the SPEC; the user approved it.
- 2026-11-11: Created the implementation PLAN; the user approved it.
- 2026-11-11: Created `TASKS.md`; beginning with A-001, the focused failing
  tests.
- 2026-11-11: A-001 red phase: the focused test run had 7 passing compatibility
  cases and 5 expected failures for missing TLS forwarding and multi-URL/TLS
  health-probe behavior.
- 2026-11-11: A-002 and A-003 implemented. The focused launcher and health-check
  suite now passes (14 tests); the final health-check review also prevents
  credentialed URLs and redirects from reusing the loopback-only TLS
  verification exception.
- 2026-11-11: A-004 updated the Mail/Wiki HTTP guides, deployment guide, and
  deployment README with local and container HTTPS setup.
- 2026-11-11: The full suite against the installed runtime 0.8.2 fails while
  loading the existing MCP agent manifest because that release predates the
  endpoint contract on this branch. Installing the local runtime checkout
  editable was not possible because the environment lacks `setuptools` and
  cannot retrieve build requirements; no repository or virtual-environment
  package changes resulted. Using the runtime source directories through
  `PYTHONPATH`, the full suite reached existing architecture failures for the
  Mail approval/entrypoint directories and was interrupted after further
  delayed failures. A focused unit run with `-x` identified a separate existing
  30-second stdio MCP timeout in `test_wiki_mcp_client.py`.
- 2026-11-11 delivery check: prepared the repository's Python 3.12 environment
  and installed the published runtime 0.8.2 distributions to match CI. Ruff
  passed, mypy passed (248 source files), and the focused HTTPS suite passed
  (14 tests). The required full pytest run fails first in
  `TestMail001Search.test_search_is_performed_and_nothing_is_written`, because
  the committed Mail manifest uses MCP endpoint fields that runtime 0.8.2 does
  not accept. The run also stalled in MCP transport tests near 67% and was
  interrupted. The origin-push skill blocks commit and push while pytest fails.

## Validation

- 2026-11-11 follow-up: installed the runtime feature branch using the
  documented `--runtime-source` option. This removes the manifest-version
  failure. After moving aside the stale empty legacy directories left by
  earlier test runs and disabling bytecode writes, the suite reaches the
  existing real-stdio test
  `TestNativeClientOverRealTransport.test_a_search_crosses_the_protocol`,
  which timed out after 30 seconds while initializing `wiki-local` inside the
  restricted execution environment.

- 2026-11-11 diagnostic: reran that exact MCP stdio test outside the restricted
  environment. It passed. This isolates the timeout to local process
  restrictions and does not justify changing the MCP client, server, or test
  fixture.

- 2026-11-11 scope update: the user authorized addressing MCP and CI blockers.
  Read-only inspection confirmed that the CI workflow checks out runtime
  release `V0.8.2`, while the Mail manifest contract is present in runtime
  commit `98c7fad26cfc8f258d57f85d511de63a22f802d8`. Revised SPEC, PLAN, and
  TASKS initially proposed pinning CI to that commit. The user declined that
  change for now and directed that CI alignment wait until after the runtime
  merge and release. The workflow remains unchanged; local checks used the
  compatible runtime source through `PYTHONPATH`.

- 2026-11-11: The full pytest run against the compatible runtime source exposed
  seven JWT tests that omitted the manifest's required MCP resource URL. Updated
  the Mail environment fixture and the temporary Wiki JWT manifests to include
  the required value. The real-stdio Wiki test passed outside local process
  isolation.

- 2026-11-11: Required local checks passed against runtime commit
  `98c7fad26cfc8f258d57f85d511de63a22f802d8`: Ruff passed; mypy reported no
  issues in 246 source files; pytest reported 2525 passed, 872 skipped, and 27
  existing deprecation warnings. The Quality workflow remains on `V0.8.2` per
  the user's instruction and needs a later update after the runtime release.

- `.venv/dev/bin/python -m pytest tests/unit/test_http_server_tls.py tests/unit/test_deploy_healthcheck.py -q`: 12 passed after implementation.
- `.venv/dev/bin/python -m ruff check tests/unit/test_http_server_tls.py tests/unit/test_deploy_healthcheck.py agents/mail/src/ai_agent_lab/mail/adapters/http/server.py agents/wiki/src/ai_agent_lab/wiki/adapters/http/server.py deploy/healthcheck.py`: passed.
- `.venv/dev/bin/python -m pytest tests/unit/test_http_server_tls.py tests/unit/test_deploy_healthcheck.py -q`: 14 passed after the health-check safety tests were added.
- `.venv/dev/bin/python -m ruff check .`: passed.
- `.venv/dev/bin/python -m mypy`: passed (248 source files); repeated with `MYPYPATH` pointing to the local runtime packages, also passed.
- `.venv/dev/bin/python -m ruff format --check` on the five changed Python files: passed.
- `git -c core.whitespace=cr-at-eol diff --check`: passed. The repository's changed Python and Markdown files use CRLF line endings.
- `PATH="$PWD/.venv/dev/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 .venv/dev/bin/python -m pytest tests/unit/wiki/test_wiki_mcp_client.py::TestNativeClientOverRealTransport::test_a_search_crosses_the_protocol -q`: passed (1 test) when run outside local process isolation; the same test timed out inside it.
- The full pytest quality gate passed using the runtime feature source through
  `PYTHONPATH`; the published `V0.8.2` package is not compatible with this
  branch's endpoint manifest and the CI update is intentionally deferred.
