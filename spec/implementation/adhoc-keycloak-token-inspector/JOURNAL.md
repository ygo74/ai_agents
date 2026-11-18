# Implementation Journal

## Approved scope

- Add a Keycloak Direct Access Grants CLI under `ai_agents/scripts/` to print
  a Bearer-compatible access token and locally decoded, unverified JWT claims.
- Update the contributor guide for MCP inspection and add deterministic tests.
- Repository: `ai_agents`; branch: `feature/37-mcp-agent-endpoints`.
- SPEC and PLAN approved by the maintainer. No Issue was requested.

## Progress

- Added `scripts/keycloak_token.py` with HTTPS OIDC discovery, Direct Access
  Grants, optional Basic client authentication, sanitized errors, and local
  unverified JWT claim display.
- Added deterministic unit coverage and updated the contributor MCP inspection
  guide. No credential or token persistence was added.

## Validation and decisions

- Passed: `./.venv/dev/bin/ruff check .`.
- Passed: `./.venv/dev/bin/python -m pytest tests/unit/test_keycloak_token.py -q`
  (22 passed).
- Passed: `./.venv/dev/bin/python -m mypy scripts/keycloak_token.py tests/unit/test_keycloak_token.py`.
- Passed: `./.venv/dev/bin/python -m scripts.keycloak_token --help`.
- Repository-wide mypy does not pass: eight errors in existing Mail and Wiki
  bootstrap modules because the installed runtime types do not declare
  `mcp_agent_operation_name` and `mcp_agent_description`.
- Repository-wide pytest does not pass: the first Mail scenario fails while
  validating `config/agents/mail/agent.yaml`; the installed runtime schema
  rejects its existing `http.mcp` configuration and MCP endpoint type. The
  focused new tests pass independently.
- Kept these unrelated runtime/CI compatibility changes out of scope, in line
  with the maintainer's direction to update CI after the runtime library is
  merged and released.
- The maintainer requested commit and push after being informed of these
  repository-wide check failures; no runtime or CI compatibility fix is in scope.
- `git diff --check` passed.
