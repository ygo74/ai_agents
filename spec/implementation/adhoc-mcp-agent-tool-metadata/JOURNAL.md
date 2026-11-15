# Implementation Journal

## Approved scope

- The user approved `SPEC.md` on 2026-11-15 and `PLAN.md` on 2026-11-15.
- Primary repository: `ai_agents`, branch `feature/37-mcp-agent-endpoints`.
- Secondary repository: `ai-enterprise-agent-runtime`, branch
  `feature/37-mcp-agent-endpoints`.
- The working trees were clean before this request record was created.
- Add optional `mcp_agent_operation_name` and `mcp_agent_description` to the
  runtime manifest contract and pass them into the hosted MCP operation. By
  default, use the agent name and description from the manifest. Internal agent
  skills remain behind the single conversational MCP operation.
- No Issue, commit, push, merge, release, or CI change is part of this scope.

## Progress

- [x] SPEC approved and recorded.
- [x] PLAN approved and recorded.
- [x] Ordered implementation tasks recorded.
- [x] Runtime manifest and MCP hosting contract implemented after red tests.
- [x] Mail/Wiki service integration and public guidance.
- [ ] Full repository pytest checks; focused checks pass, but full suites did not complete (details below).
- [x] Final review of both repository diffs; `git diff --check` passed with CRLF-aware whitespace handling.

## Decisions and validation

### Runtime manifest and endpoint

- Added manifest input/schema/loader tests first. The initial command
  `.venv/bin/python -m pytest tests/integration/python/test_manifest_configuration_schemas.py -q`
  failed on the unrecognized override fields (5 failed, 11 passed), confirming
  the expected gap.
- Added the optional typed manifest fields and packaged JSON Schema, preserving
  the existing schema identifier because both additions are optional. The
  focused schema tests then passed: 16 passed.
- Added MCP endpoint cases for descriptor defaults and independent name and
  description overrides, plus a native definition contract test. The first run
  failed because the hosting and definition APIs did not yet accept the values
  (4 failed, 3 passed).
- Implemented pass-through from `AgentDefinition` and `HostingFactory` to
  `McpAgentEndpoint`; the operation name and description remain separate from
  the provider-neutral discovery descriptor.
- Current focused runtime result:
  `.venv/bin/python -m pytest tests/integration/python/test_manifest_configuration_schemas.py tests/integration/python/test_mcp_agent_endpoint.py tests/integration/python/test_native_agent_definition.py -q`
  — 23 passed.
- Runtime documentation and sample updates are complete. Full repository
  quality gates remain to be completed.

### Mail and Wiki integration

- Added real service tests for default tool metadata, custom name/description
  overrides, unchanged discovery IDs, and MCP invocation through the advertised
  Mail operation. The override test failed before wiring: it advertised
  `mail-agent` rather than `mailbox_assistant`.
- Passed both optional values from each loaded `AgentManifest` into its
  `AgentDefinition`. Mail and Wiki override tests then passed, along with
  manifest-default listing tests. The Mail override test also invoked its
  configured operation successfully through the discovery-based test helper.
- Focused final result:
  `.venvs/dev312/bin/python -m pytest tests/contract/test_mail_service_configuration.py::TestTheServiceRefusesToRunOpen::test_manifest_selects_the_api_key_and_exposes_declared_routes tests/contract/test_mail_service_configuration.py::TestTheServiceRefusesToRunOpen::test_manifest_overrides_the_mcp_operation_metadata tests/contract/test_wiki_openai_http_surface.py::test_wiki_mcp_defaults_operation_metadata_from_manifest tests/contract/test_wiki_openai_http_surface.py::test_wiki_mcp_uses_manifest_operation_metadata_overrides -q`
  — 4 passed.
- An isolated existing Wiki multi-caller MCP conversation test did not finish
  within approximately 60 seconds and was interrupted. The metadata listing
  tests passed; the full suite will determine whether this remains a blocker.
- Ruff on the changed Python files in both repositories passed after a minor
  test-formatting fix. Full checks remain to be completed.

### Repository validation and review

- Runtime full Ruff passed:
  `.venv/bin/python -m ruff check packages/python tests`.
- Runtime focused tests passed after the final source review:
  `.venv/bin/python -m pytest tests/integration/python/test_manifest_configuration_schemas.py tests/integration/python/test_mcp_agent_endpoint.py tests/integration/python/test_native_agent_definition.py -q`
  — 23 passed.
- Runtime full pytest was started with results directed to
  `/tmp/runtime-mcp-agent-metadata-pytest.xml`. It advanced into
  `tests/integration/python/test_agentframework_binding.py` but produced no
  further output or final summary for about a minute, so it was interrupted.
- `ai_agents` full Ruff passed:
  `.venvs/dev312/bin/python -m ruff check .`.
- The first full mypy attempt reported missing `py.typed` markers because the
  local runtime packages were installed editably. I built wheels from the
  current runtime working tree and installed those local wheels into the
  `ai_agents` validation environment, matching the quality workflow's package
  installation model. Mypy then passed: `Success: no issues found in 246
  source files`.
- `ai_agents` focused Mail/Wiki MCP tests passed in that wheel-backed
  environment — 4 passed. These cover manifest-derived defaults, explicit
  overrides, and Mail invocation through the discovered operation name.
- Explicit schema validation of every delivered `ai_agents` manifest passed:
  `tests/integration/test_delivered_configuration.py::test_every_delivered_manifest_matches_the_runtime_json_schema`
  — 32 passed.
- `ai_agents` full pytest collected 3,409 tests. It reached the unmodified
  `tests/contract/test_mcp_connection.py::TestOneConversationOpensOneSession::test_concurrent_callers_get_the_same_session`
  test, which reported `FAILED` after its configured 30-second timeout; the
  process then stopped making progress during shutdown and was interrupted.
  The command yielded no traceback or JUnit summary, so the exact failure cause
  is not established. This MCP stdio client test is outside the metadata code
  changed here.
- Both repositories contain CRLF-indexed files. The ordinary `git diff
  --check` treats their carriage returns as trailing whitespace; the equivalent
  CRLF-aware check, `git -c core.whitespace=cr-at-eol diff --check`, passed in
  each repository.
- No commit, push, merge, CI workflow change, or release was performed.
