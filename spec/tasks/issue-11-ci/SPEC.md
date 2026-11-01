# Specification

## Issue

PR #11 in `ygo74/ai_agents` (`feat(agents): configure HTTP hosts from manifests`).
The Quality run [41329545952](https://github.com/ygo74/ai_agents/actions/runs/41329545952)
fails in its test step. This work is tracked with the PR because there is no
separate `ai_agents` issue for these CI failures. Runtime issue #34 is related
to the feature but is not the tracker for this repair.

## Objective

Make the test suite and repository boundaries accurately reflect the manifest
driven HTTP configuration and per skill MCP routing in PR #11, and remove
environment dependent test behavior so the CI job is reproducible.

## Context and problem

The run uses `ai-enterprise-agent-runtime` 0.8.2. Lint and mypy pass; the test
step reports 9 failures. The failures are concentrated in:

- `agents/core/src/ai_agent_lab/core/config/mcp_backend.py`, which is unused
  and imports runtime configuration and manifest domains forbidden to `core`;
- tests that assume Mail HTTP authentication comes from an API key environment
  variable even though the delivered Mail manifest selects JWT;
- two Mail console profiles in `.vscode/launch.json` that hardcode an env file
  instead of using the existing `mailAgentEnvFile` input;
- MCP selection tests that treat `server_for` as the active per skill router,
  while execution routes each skill through the MCP registry;
- a Wiki routing test whose `WikiMcpSettings` implicitly reads local `.env`
  values, so its identity assertion differs between local runs and CI.

## Scope

- Remove the unused core-level single MCP backend selector and update the
  obsolete selection tests to cover the documented legacy `server_for`
  behavior. Keep and rely on the existing Mail and Wiki registry routing tests
  for per skill routing and multi-server behavior.
- Make Mail HTTP authentication tests use an isolated API-key manifest fixture
  when they are testing the API-key path. Keep the delivered Mail manifest's
  JWT selection unchanged and test startup refusal against the fixture's
  actual authentication policy.
- Update the two Mail console launch profiles to pass `${input:mailAgentEnvFile}`
  using `--env-file`, consistently with the other Mail profiles and the
  integration test.
- Make the Wiki routing fixture provide caller identity settings explicitly
  and disable implicit `.env` loading for those settings.
- Change only `ai_agents`; do not alter runtime behavior, runtime version,
  production agent manifests, or documentation unless implementation review
  shows a required test instruction needs correction.

## Out of scope

- Changing the Mail deployment from JWT to API-key authentication.
- Changing the per-skill MCP routing implementation or runtime 0.8.2.
- Updating unrelated test failures or expanding the feature in PR #11.
- Committing, pushing, or merging changes as part of this specification gate.

## Expected behavior

1. Core contains no unused MCP selector importing runtime configuration or
   manifest modules.
2. Legacy `server_for` tests assert its documented compatibility behavior;
   normal Mail and Wiki operations continue to route using each skill's
   registry binding.
3. Mail API-key tests exercise an API-key manifest in an isolated fixture,
   while the delivered manifest remains JWT-configured.
4. All Mail console profiles use the selectable environment file input.
5. Wiki routing tests use explicit identity configuration and pass regardless
   of a developer's local `.env` contents.

## Architecture, interfaces, and data

No production service interfaces or manifest schemas change. Test-only
configuration is isolated under temporary directories. MCP routing remains
owned by `MailToolsProvider` / `WikiToolsProvider` registry resolution for each
skill; the `server_for` helpers remain single-server compatibility accessors.

## Constraints and decisions

- Preserve the clean working tree and current PR branch; include no unrelated
  edits.
- Preserve the authentication mode declared by `config/agents/mail/agent.yaml`.
- Tests must not rely on `.env` files in the workspace.
- The exact test fixture mechanics may follow existing temporary-manifest
  patterns in the contract tests.

## Acceptance criteria

1. All previously failing test cases in the linked CI job pass locally.
2. The complete Quality job passes on the updated PR head, including lint,
   type-check, and tests.
3. Existing per-skill Mail and Wiki routing coverage remains in place and
   passes.
4. The production Mail manifest continues to select JWT and no runtime
   dependency is changed.

## Validation strategy

- Run focused architecture, MCP selection, Mail service configuration,
  Mail environment selection, and Wiki registry routing tests.
- Run the repository's documented lint, type-check, and full test commands
  before reporting completion.
- Confirm the final diff is limited to this specification's scope.

## Risks and open questions

- The removed selector is not referenced by production code; verify repository
  imports before deleting it.
- The API-key test fixture must set the configuration directory explicitly so
  the local `.env` and the delivered JWT manifest cannot affect its result.
