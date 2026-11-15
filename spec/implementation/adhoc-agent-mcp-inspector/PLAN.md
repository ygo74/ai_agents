# Implementation Plan

## Approved SPEC

Implement the approved [SPEC](SPEC.md): add a developer command that connects
to a hosted Mail or Wiki MCP endpoint, lists its tools, and displays their
descriptions and input schemas. The command is read-only and must not call
`invoke_agent`.

## Existing architecture and reuse analysis

- `agents/mail/src/ai_agent_lab/mail/adapters/cli/discover.py` inspects Mail's
  downstream MCP server. It is tied to Mail configuration and is not suitable
  for inspecting either hosted agent endpoint.
- Hosted Mail and Wiki endpoints expose Streamable HTTP at `/mcp`. The existing
  `tests/support/mcp_http.py` uses the SDK's `streamable_http_client` and
  `ClientSession` to connect to that surface.
- Mail's checked-in host configuration uses JWT bearer authentication; it can
  also be configured for API-key authentication. Wiki's checked-in host
  configuration uses `X-API-Key`. A generic header-name/environment-variable
  option will cover both without making the inspector load either agent's
  configuration or depend on framework-specific packages.
- The MCP SDK is already a dependency of the Mail and Wiki distributions and is
  present in the repository development environment. No runtime package,
  framework, or CI dependency change is needed.
- `doc/contributors/mcp-clients.md` is the existing developer guide for MCP
  client usage and is the appropriate place for both command examples.

## Repository and component scope

- Add `scripts/inspect_mcp.py`, runnable as
  `python -m scripts.inspect_mcp` from the repository root.
- Add focused unit coverage under `tests/unit/` for authentication header
  resolution, readable tool/schema output, read-only discovery, failure exit
  behavior, and connection cleanup.
- Add Mail and Wiki setup examples to `doc/contributors/mcp-clients.md`.
- Update this request's `TASKS.md` and `JOURNAL.md` as implementation proceeds.
- Do not change agent hosts, runtime APIs, manifests, deployment settings,
  downstream MCP discovery, or CI.

## Ordered steps and dependencies

1. Add failing focused tests for argument parsing, environment-sourced headers,
   tool rendering (name, description, argument metadata and complete schema),
   discovery-only behavior, error reporting, and session/transport cleanup.
2. Implement the inspector CLI with `argparse`, the MCP SDK's Streamable HTTP
   client and `ClientSession`. Require an endpoint URL. Accept repeatable
   `--header HEADER_NAME=ENVIRONMENT_VARIABLE` options; resolve values only
   from the process environment, reject missing/empty values, and never print
   them. This supports `Authorization` with a complete `Bearer ...` value for
   Mail and `X-API-Key` for Wiki without placing secrets on the command line.
3. Initialize one client session, call only `list_tools`, render every returned
   tool and its declared input schema, and close the session and transport on
   every path. Keep schema rendering generic: do not hardcode `invoke_agent`
   or any Mail/Wiki tool names. Retain normal SDK TLS verification for HTTPS.
4. Return a non-zero process status on configuration, connection,
   authentication, or protocol failure. Keep output useful while excluding
   header values and avoiding an invocation of any discovered tool.
5. Add documented PowerShell examples for local HTTPS Mail and Wiki servers in
   the contributor MCP guide, including the required environment variables
   and example header mappings.
6. Run Ruff on changed Python files and the focused pytest tests; then review
   the diff and record actual commands/results in `JOURNAL.md`.

## Test-first validation

- Use fake MCP session/transport boundaries so the unit tests do not require a
  running agent, identity provider, or external service.
- Assert that the only MCP request is `list_tools`; the fake must fail if a
  tool invocation is attempted.
- Assert that a configured secret is not present in standard output or error
  output, including on a failed connection.
- Run `ruff check` on the changed scripts/tests and the repository pytest
  command for the new unit test module.

## Security and deployment impact

- No server or authentication policy changes. The user obtains a Mail bearer
  token through the existing identity-provider workflow; Wiki uses its
  configured API key.
- Credentials are supplied as process environment values and are not accepted
  as literal option values. The command does not log request headers.
- HTTPS uses the MCP SDK's default certificate verification. No insecure TLS
  option, OAuth token acquisition, state retention, or deployment artifact is
  introduced.
- The command only initializes MCP and lists tool metadata. It does not send
  agent messages or touch mailbox/wiki data.

## Documentation and examples

Add a section to `doc/contributors/mcp-clients.md` with commands for:

- Mail at `https://127.0.0.1:8123/mcp`, using an environment variable holding
  the full `Authorization: Bearer ...` header value.
- Wiki at `https://127.0.0.1:8124/mcp`, using the `X-API-Key` header and the
  configured Wiki API key environment variable.

Document that the command displays tools and schemas only, and requires the
HTTPS certificate to be trusted by the running Python environment.

## Risks and completion criteria

- The tool schema returned by the MCP SDK is a typed model; rendering must
  serialize the complete schema rather than assume a fixed argument layout.
- The service may return an MCP error after HTTP authentication succeeds;
  preserve a useful failure status without exposing configured secret values.
- Complete when both documented commands can inspect their respective hosted
  endpoint, report its live tool metadata, and fail safely for missing
  credentials or unavailable services. No tool is invoked.
