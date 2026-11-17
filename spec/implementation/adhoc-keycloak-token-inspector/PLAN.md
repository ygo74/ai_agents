# Implementation Plan

## Approved SPEC

Implement the approved [SPEC.md](SPEC.md): add a standalone CLI in
`ai_agents/scripts/` that obtains a Keycloak access token with Direct Access
Grants, prints it in Bearer form, and displays locally decoded JWT claims.
Keep the change in `ai_agents`; no Issue or runtime repository change is in
scope.

## Existing architecture and reuse analysis

- `scripts/inspect_mcp.py` is the closest CLI precedent. It uses `argparse`,
  exposes a callable `main(arguments=...)` for deterministic tests, verifies
  TLS explicitly, and sanitizes remote errors rather than printing exception
  messages.
- `httpx` is already included in the repository development dependencies and
  is used by the MCP inspector. Reuse it for OIDC discovery and token exchange;
  do not add a dependency.
- Unit tests live in `tests/unit/`. Follow the inspector's approach of
  replacing the network boundary in tests so no live Keycloak server is needed.
- The contributor guide already has an “Inspect tools exposed by a hosted
  agent” section. Extend that section with the token helper and retain its
  existing endpoint inspection guidance.
- This is a developer CLI with no retained state or agent framework boundary.
  Keep it standalone; avoid new packages, agent abstractions, token storage,
  or runtime API changes.

## Repository and component scope

- `scripts/keycloak_token.py`: CLI arguments, OIDC discovery, password-grant
  token exchange, sanitized error handling, and JWT claim display.
- `tests/unit/test_keycloak_token.py`: deterministic unit coverage for parsing,
  discovery, request construction, claim decoding, and failure handling.
- `doc/contributors/mcp-clients.md`: setup, invocation, and output/security
  guidance for using the token with the existing MCP inspector.
- `spec/implementation/adhoc-keycloak-token-inspector/`: this plan and the
  task checklist/journal created after plan approval.

## Ordered steps and dependencies

1. Add focused unit tests for issuer validation and OIDC discovery. Require an
   HTTPS issuer, validate the discovered issuer against the configured issuer,
   require an HTTPS token endpoint, and sanitize discovery/network failures.
2. Add tests for the password-grant request. Submit `grant_type=password`,
   username, password, and the requested scope when supplied. For a public
   client, send `client_id` in the form; when a client secret is present, use
   HTTP Basic client authentication with the client ID and secret. Never put
   credentials in a URL, and do not include secret values in diagnostics.
3. Implement the smallest CLI and HTTP boundary needed to support the tests.
   Keep configuration typed and secret-bearing fields out of object
   representations. Reuse an injected HTTP transport boundary for deterministic
   tests; use an `httpx` adapter in production with certificate verification
   enabled and a finite timeout.
4. Add tests for successful output and token errors. Print a copyable
   `Bearer <access_token>` line, then pretty-print decoded claims for a
   three-part JWT. Do not label claims as verified. For opaque tokens, JWE, or
   invalid claim payloads, print the access token and a clear claims-unavailable
   explanation without attempting decryption or signature verification.
5. Ensure malformed configuration, rejected grants, malformed responses, and
   transport failures return a non-zero status with an actionable, sanitized
   message. Do not print the username, password, client secret, raw response,
   or token in error messages; do not persist tokens.
6. Document required Keycloak Direct Access Grants setup, all CLI arguments,
   shell-variable examples, Bearer token output, unverified claim limits, the
   impact of MFA/required actions, and process-list visibility of expanded
   argument values.

## Test-first validation

- Use deterministic fake HTTP responses/transports to test OIDC discovery and
  token exchange; tests must not contact Keycloak or an online decoder.
- Cover the public-client and confidential-client request shapes, optional
  scope and timeout, issuer mismatch, non-HTTPS endpoints, rejected grants,
  malformed discovery/token responses, JWT and opaque/JWE values, and secret
  redaction from CLI errors.
- Run the focused test module first, then the repository's documented Python
  gates: `python -m ruff check .`, `python -m mypy`, and
  `python -m pytest --junitxml=test-results.xml`. Report only commands that
  were actually run.

## Security and deployment impact

- Use HTTPS and normal certificate verification for discovery and token
  requests; do not expose a flag to disable verification.
- Keep passwords and client secrets out of URLs, logs, persisted files, and
  diagnostics. Mark secret-bearing fields as non-representable where applicable.
- Access-token display is intentional and limited to stdout after successful
  authentication. Decoded JWT claims are unverified local display data; the
  MCP server remains responsible for validating issuer, audience, signature,
  and expiry.
- Shell-variable expansion avoids placing literal values in shell history, but
  expanded arguments can remain visible through operating-system process
  inspection. Document this operator responsibility as requested.
- Direct Access Grants must be enabled for the selected Keycloak client and do
  not support interactive MFA or required-action flows.

## Documentation and examples

Extend the contributor MCP guide with a PowerShell example that reads
username/password and an optional client secret from environment variables,
calls `python -m scripts.keycloak_token`, then passes the displayed Bearer
value to `scripts.inspect_mcp`. State explicitly that the CLI prints an access
token and unverified claims and does not decrypt encrypted JWTs or validate
signatures.

## Risks and completion criteria

- Keycloak clients without Direct Access Grants, or user accounts requiring an
  interactive flow, will reject this grant. Return a safe actionable message
  without echoing the server's raw response.
- A token may be opaque or encrypted and therefore have no locally displayable
  JWT claims. Preserve the token output and explain this condition.
- Shell-expanded argument values may be visible in process listings; this is
  an accepted trade-off in the approved SPEC and must be documented.
- Completion requires all scoped code, tests, and contributor documentation;
  required Python checks pass; and the output/error paths do not expose
  credentials or persist tokens.
