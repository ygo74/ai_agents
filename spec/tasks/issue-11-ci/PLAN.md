# Implementation Plan

## Issue and SPEC

- Tracking item: `ygo74/ai_agents` PR #11 and its failing Quality run
  [41329545952](https://github.com/ygo74/ai_agents/actions/runs/41329545952).
- Approved specification: [`SPEC.md`](SPEC.md).

## Objective

Correct the stale and environment dependent test assumptions identified in the
SPEC, remove the unused core-level MCP selector, and leave PR #11 with a
reproducible passing quality run.

## Repositories and prerequisites

- Work only in `/data/repos/ai_agents`.
- Continue on the existing PR branch `feature/34-agent-http-manifest`.
- Preserve the approved SPEC and any unrelated local work; do not touch the
  `ai-enterprise-agent-runtime` repository or change the runtime pin.

## Steps

### Step 1 — Remove the unused core selector and correct selection tests

- Objective: Keep core within its declared runtime import boundary and make
  tests distinguish the legacy single-server helper from per-skill routing.
- Files or components:
  - `agents/core/src/ai_agent_lab/core/config/mcp_backend.py`
  - `tests/unit/test_mcp_backend_selection.py`
  - Existing routing coverage in `tests/unit/test_mail_registry_routing.py`
    and `tests/unit/wiki/test_wiki_registry_routing.py`
- Change: Confirm no production or test consumer imports the core selector,
  then remove it. Update the selection tests to assert the documented
  `server_for` compatibility behavior. Keep the registry routing tests intact
  as the proof that individual skills may use separate MCP servers.
- Validation: Run the architecture boundary test, the selection tests, and
  both registry routing modules.

### Step 2 — Isolate Mail API-key contract fixtures

- Objective: Keep tests of the API-key HTTP path independent from the
  production Mail manifest, which selects JWT.
- Files or components:
  - `tests/contract/test_mail_service_configuration.py`
  - Temporary configuration and manifest selection helpers used by that test
- Change: Build the tested API-key policy from an isolated temporary config
  directory and set its selection explicitly. Exercise the missing-key startup
  refusal and authenticated API-key request against that same policy. Leave
  `config/agents/mail/agent.yaml` unchanged.
- Validation: Run the Mail service configuration contract test and OIDC
  lifecycle tests for Mail and Wiki.

### Step 3 — Make launch and Wiki fixtures deterministic

- Objective: Remove the remaining mismatches and implicit local environment
  reads called out in the SPEC.
- Files or components:
  - `.vscode/launch.json`
  - `tests/integration/test_mail_environment_selection.py`
  - `tests/unit/wiki/test_wiki_registry_routing.py`
- Change: Point both Mail console profiles at `${input:mailAgentEnvFile}` via
  `--env-file`. In the Wiki routing fixture, pass explicit `WikiMcpSettings`
  and disable `.env` loading for settings used by the identity assertion.
  Keep the integration assertion that checks all Mail profiles.
- Validation: Run Mail environment selection and Wiki registry routing tests
  with local `.env` values absent from the fixture configuration.

### Step 4 — Run repository quality checks and update PR #11

- Objective: Verify the complete scope against the same checks used by CI.
- Files or components: Final review of all changed files and
  `spec/tasks/issue-11-ci/`.
- Change: Inspect the full diff and working tree, confirm the production Mail
  manifest and runtime dependency are unchanged, then commit the scoped changes
  and push the existing PR branch. Do not force-push or merge.
- Validation, in the repository's CI order:
  1. `python -m ruff check .`
  2. `python -m mypy`
  3. `python -m pytest --junitxml=test-results.xml`
  4. Re-run the updated GitHub Actions Quality workflow on PR #11 and confirm
     its result.

## Tests and final validation

Before full checks, run this focused selection:

```text
python -m pytest \
  tests/architecture/test_distribution_boundaries.py \
  tests/unit/test_mcp_backend_selection.py \
  tests/unit/test_mail_registry_routing.py \
  tests/unit/wiki/test_wiki_registry_routing.py \
  tests/contract/test_mail_service_configuration.py \
  tests/contract/test_oidc_http_lifecycle.py \
  tests/integration/test_mail_environment_selection.py
```

Then run the full lint, type-check, and test commands listed in Step 4. Report
only checks that actually ran, along with any environment or CI limitations.

## Risks and decisions

- The API-key contract fixture must select its temporary configuration
  explicitly; otherwise a local `.env` or the delivered JWT manifest could
  mask a regression.
- The core selector can be removed only after confirming `rg` finds no
  remaining imports or references outside its obsolete unit test.
- If the approved scope proves insufficient to make the job pass, stop and
  request a SPEC update before expanding the implementation.

## Completion criteria

- All focused tests and the repository quality checks pass.
- The new GitHub Actions Quality run on PR #11 succeeds.
- The diff changes only files covered by the approved SPEC and this PLAN.
- The existing PR branch contains the reviewed commit; no merge or force-push
  is performed.
