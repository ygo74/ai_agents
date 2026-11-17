# Specification

## Request source and repositories

- Request: ad hoc request from the repository maintainer; no Issue was requested.
- Primary repository: `ai_agents`, which owns the MCP inspection script and its usage documentation.
- No secondary repository is required.
- Work will use the current branch `feature/37-mcp-agent-endpoints` unless the maintainer selects another branch.

## Objective and current context

The existing `scripts.inspect_mcp` client can list tools from an MCP server, but a user must obtain an access token from LibreChat's browser developer tools and copy it into the shell before inspection. This is inconvenient and exposes the token during manual handling.

Add a separate CLI utility under `scripts/` that authenticates a user against Keycloak through OIDC, prints the resulting access token for use as a Bearer credential, and displays the token's decoded claims for local inspection.

## Scope and exclusions

- Add a Python CLI utility under `scripts/` that accepts OIDC configuration through command-line options.
- Use OIDC discovery from a configured Keycloak realm issuer and the Resource Owner Password Credentials grant (Keycloak Direct Access Grants).
- Send the username, password, client ID, and optional client secret to the discovered token endpoint and display the `access_token`.
- Decode and pretty-print JWT access-token claims locally. A signed JWT is encoded, not encrypted; the utility will not claim to verify its signature or decrypt a JWE.
- Update the contributor guide for MCP inspection with Keycloak client setup, invocation examples, and output handling.
- Add deterministic tests for discovery, the password-grant request, JWT claim decoding, and error paths without contacting a live Keycloak server.
- Do not change `ai-enterprise-agent-runtime` or the MCP server itself.
- Exclude Authorization Code/PKCE, client-credentials grant, token introspection, signature verification, automatic audience rewriting, token persistence, and online decoding services.

## Expected user behavior

The user runs the script with an issuer URL, client ID, username, password, optional client secret, and optional scopes/timeout. The script requests a token from Keycloak, then prints the access token and its decoded claims. The token is held only in process memory and is not written to a file or emitted to logs.

The client must have Direct Access Grants enabled in Keycloak. The requested audience and roles remain governed by that Keycloak client's scopes and mappers.

## Architecture, permissions, and data

- Keep the utility standalone and based on the standard library where practical; reuse repository dependencies only where already justified.
- Use TLS with normal certificate verification for discovery and token requests.
- Send a supplied client secret only as client authentication to the token endpoint; never include it in a URL or diagnostic output.
- Do not log or echo the username, password, client secret, access token, or raw token endpoint response.
- Treat decoded claims as unverified display data. Do not present the output as proof of signature validity, audience acceptance, or server authorization.
- Print the access token because the user explicitly requested it. Never place it in command arguments, files, logs, or error messages.

## Constraints and decisions

- Proposed CLI inputs: `--issuer-url`, `--client-id`, `--username`, `--password`, optional `--client-secret`, optional `--scope`, and optional `--timeout`.
- Use Keycloak Direct Access Grants because the user explicitly wants credentials supplied through CLI arguments. The grant must be enabled for the selected client.
- If `--client-secret` is supplied, authenticate the client using HTTP Basic at the token endpoint; omit it for a public client.
- Credential arguments can be populated from shell variables to avoid writing literal secrets in shell history. After shell expansion, argument values may still be visible to process inspection tools; protecting the local invocation is the operator's responsibility.
- The access token may be an opaque token or an encrypted JWE. In those cases, print the token and a clear message that claims cannot be decoded; do not attempt decryption.
- OIDC discovery issuer must match the configured issuer, and TLS verification cannot be disabled by a CLI flag.

## Acceptance criteria

1. The utility accepts OIDC settings through CLI arguments and reports actionable errors for invalid or missing values.
2. It discovers Keycloak's token endpoint from the issuer metadata over verified TLS.
3. It submits the password grant with supplied credentials and, when present, authenticates the client with its secret.
4. It displays the access token in a copyable Bearer-compatible form.
5. For a three-part JWT, it decodes and pretty-prints claims without labeling them verified; for opaque/JWE tokens it explains why claims are unavailable.
6. Credentials, tokens, and raw token endpoint responses are absent from logs and error messages; no token is persisted.
7. Automated tests cover successful and rejected grants without live identity-provider access.
8. Contributor documentation explains Keycloak Direct Access Grants, script usage, claims decoding limits, and argument visibility.
9. Ruff, mypy, and pytest for `ai_agents` pass according to the repository's current Python gates.

## Validation impact

- Ruff and strict mypy for the repository.
- Focused unit/contract tests with fake OIDC discovery and token endpoints.
- Full pytest suite according to the repository delivery workflow.
- Review that token contents do not appear in test output, captured server logs, or exception messages.

## Risks and open decisions

- Keycloak must have Direct Access Grants enabled for the selected client. This grant does not support interactive browser SSO steps such as MFA or required-action screens; use an account/client configuration that permits the grant.
- JWT claim decoding is not signature verification. The MCP server remains responsible for validating issuer, audience, signature, and expiry.
- Argument values expanded from shell variables may be visible to local process inspection. The script will not persist or print credentials, but cannot hide values from operating-system process listings.
