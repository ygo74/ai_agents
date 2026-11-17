# Implementation Tasks

- [x] AGENTS-001 Add failing tests for HTTPS issuer validation and OIDC
  discovery; completion: issuer mismatch, invalid schemes, discovery errors,
  and TLS verification are observable without a live server; depends on: none.
- [x] AGENTS-002 Add failing tests for public and confidential password grants;
  completion: request form, Basic client authentication, optional scope and
  timeout, token parsing, and sanitized failures are asserted; depends on:
  AGENTS-001.
- [x] AGENTS-003 Add failing tests for JWT claim decoding and CLI output;
  completion: valid JWT claims are pretty-printed as unverified, opaque/JWE
  values explain the limitation, and secrets/token responses are absent from
  error output; depends on: AGENTS-002.
- [x] AGENTS-004 Implement `scripts/keycloak_token.py`; completion: the approved
  CLI uses verified HTTPS, finite timeouts, Direct Access Grants, safe output,
  and does not persist credentials or tokens; depends on: AGENTS-001,
  AGENTS-002, AGENTS-003.
- [x] AGENTS-005 Document Keycloak setup and MCP inspection usage;
  completion: contributor guide explains required client configuration, all
  arguments, shell-variable invocation, token/claims limits, and process-list
  visibility; depends on: AGENTS-004.
- [ ] AGENTS-006 Run Python quality gates and review secret-handling paths;
  completion: focused tests, Ruff, mypy, and full pytest pass, and output/error
  behavior matches the approved SPEC; depends on: AGENTS-004, AGENTS-005.
  Current: Ruff, focused pytest, and focused mypy pass. Repository-wide mypy
  and pytest are blocked by the checked-in MCP/runtime API mismatch recorded in
  `JOURNAL.md`.
