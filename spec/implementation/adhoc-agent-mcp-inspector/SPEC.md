# Specification

## Request source and repositories

- Source: ad hoc user request; no Issue is required or to be created.
- Primary repository: `ai_agents`.
- Affected services: the Mail Agent and Wiki Agent MCP endpoints hosted by this
  repository.

## Objective and current context

Provide a small diagnostic client that lets a developer connect to either
hosted agent over MCP and inspect the operations exposed by that agent. The
developer needs to see the operation name, its description, and the argument
schema, including argument descriptions when the server supplies them.

The existing `ai_agent_lab.mail.adapters.cli.discover` command inspects the
Mail Agent's configured downstream MCP server (such as Gmail). It does not
inspect the Mail Agent or Wiki Agent's own hosted `/mcp` endpoints. The hosted
endpoints use Streamable HTTP and currently expose an `invoke_agent` tool.

## Scope and exclusions

In scope:

- Add a developer-facing MCP inspection client in `ai_agents` that connects to
  a selected Mail or Wiki hosted MCP endpoint over Streamable HTTP.
- Query the MCP tool catalogue only, then print a readable report containing
  each tool name, description, and complete input schema. Preserve required
  fields, types, nested properties, and schema descriptions as returned by the
  server.
- Accept the endpoint URL and authentication configuration without embedding
  credentials in source code or printing them. Support the current Mail bearer
  authentication and Wiki API-key authentication, and allow HTTPS endpoints
  with normal certificate verification.
- Report connection, authentication, and MCP protocol errors clearly and exit
  unsuccessfully when inspection cannot complete.
- Document how to run the client against both local agent hosts.

Out of scope:

- Calling `invoke_agent` or any business operation; inspection is read-only and
  must not create a conversation or trigger agent work.
- Changing either hosted endpoint, authentication policy, runtime dependency,
  CI, or downstream MCP discovery behavior.
- Acquiring OAuth tokens or bypassing TLS certificate validation.

## Expected user behavior

- The developer starts the Mail Agent or Wiki Agent and provides its `/mcp`
  URL and the required authentication value through an environment variable.
- The client performs MCP initialization and `list_tools`, then prints all
  returned tools with their descriptions and input schemas in a readable form.
- The client does not print authentication values and does not invoke a tool.
- If the service is unreachable, authentication fails, or MCP negotiation
  fails, the client reports which inspection failed and exits with an error.

## Architecture, permissions, and data

- Keep this developer utility outside agent domain and application layers; it
  must not be coupled to Mail or Wiki business models or their downstream MCP
  dialects.
- Use the MCP Python SDK's Streamable HTTP client already used by the agent
  distributions. Keep connection lifecycle bounded to one inspection and close
  the session/transport on success or failure.
- Send only the configured authentication header. Do not log credentials or
  agent conversation content. The client must not submit a message to the
  hosted agent.
- Use standard TLS certificate verification for HTTPS.

## Constraints and decisions

- The hosted endpoints are `/mcp`; Mail currently requires a bearer token and
  Wiki currently requires the `x-api-key` header. The URL and secret values
  must be supplied at runtime, not committed.
- The displayed schema is the authoritative response from `list_tools`; the
  utility must not infer or hardcode an operation catalogue.
- Keep the interface usable for both services and allow an explicit URL so the
  same utility works with local HTTP and deployed HTTPS hosts.

## Acceptance criteria

1. A developer can inspect Mail and Wiki using the same client with their
   respective endpoint and authentication configuration.
2. The report shows every tool returned by `list_tools`, its name, its
   description, and its full input schema, including descriptions and required
   status encoded by the schema.
3. The client never invokes `invoke_agent` or another listed tool.
4. Authentication values are obtained without requiring them as literal
   command-line arguments and are never included in output.
5. HTTPS is supported with normal certificate validation; no insecure TLS
   switch is added.
6. Connection and protocol failures produce a useful error and a non-zero exit
   status, and the transport is closed.
7. Contributor documentation contains example commands for inspecting the
   Mail and Wiki hosts.

## Validation impact

- Add focused tests using a local/fake MCP transport for tool rendering,
  authentication-header construction, read-only behavior, error reporting,
  and transport cleanup.
- Run the repository's Ruff checks and relevant pytest tests during
  implementation, as required by the repository delivery workflow if a commit
  is later requested.

## Risks and open questions

- Mail's bearer token must already be available to the developer; token
  acquisition remains the responsibility of the existing identity-provider
  workflow.
- MCP SDK schema model shapes may differ from plain dictionaries. The plan
  should inspect the installed SDK surface and preserve the complete schema
  without depending on agent-specific models.
