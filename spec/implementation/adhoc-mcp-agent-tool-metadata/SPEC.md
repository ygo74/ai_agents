# Specification

## Request source and repositories

- Request: ad hoc request from the repository maintainer; no Issue was requested.
- Primary repository: `ai_agents`, which owns the Mail and Wiki agent manifests,
  MCP hosting use, tests, and user-facing configuration guidance.
- Secondary repository: `ai-enterprise-agent-runtime`, which owns the shared
  Python manifest contract, packaged JSON Schema, and generic MCP endpoint.
- The repositories retain independent branches and Git histories. This file is
  the single request record and remains in `ai_agents`.

## Objective and current context

The hosted Mail and Wiki agents currently each expose one MCP tool named
`invoke_agent` with the same generic description. A caller connecting to
multiple hosted agents cannot distinguish their intended use from the tool
metadata.

The generic endpoint registers that name and description in
`McpAgentEndpoint`. Both agents already declare a useful `name` and `description`
in `config/agents/<agent>/agent.yaml`, and the runtime validates that manifest
against a versioned packaged JSON Schema.

## Scope and exclusions

- Add optional top-level `mcp_agent_operation_name` and
  `mcp_agent_description` fields to `agent.yaml`. The first name corrects the
  apparent spelling slip `mpc_agent_peration_name` in the request.
- When omitted, use the manifest's existing `name` as the MCP operation name
  and its `description` as the MCP operation description.
- When supplied, each optional field overrides only its corresponding MCP
  operation metadata. It does not change the agent's identity in discovery or
  its server identity.
- Add both optional fields to the runtime typed manifest inputs and packaged
  schema, and pass their resolved values into the generic MCP endpoint.
- Keep the MCP interaction conversational: one operation invokes the agent;
  this change does not expose the agent's individual skills as MCP operations.
- Do not automatically enumerate skill operations in the description. The
  manifest-level description is the curated routing summary, while the set of
  effective internal skills may be filtered at runtime and is not the MCP
  server's public operation list.
- Update relevant configuration/MCP documentation and tests in both
  repositories.
- No new configuration is required for Mail or Wiki: their existing manifest
  metadata supplies the defaults unless a maintainer chooses to add overrides.

## Expected behavior

An MCP client listing a hosted agent's tools sees the manifest agent name as
the tool name and the manifest agent description as the tool description by
default. A developer may customize either value independently with the new
optional fields. Invalid explicit values are rejected by manifest validation
before hosting starts. Other endpoint behavior, arguments, authentication, and
conversation handling remain unchanged.

## Architecture, permissions, and data

The runtime remains the owner of manifest validation and MCP endpoint
registration. `ai_agents` supplies delivered YAML and exercises the shared
contract. No identity, authorization, conversation, security, or retained
state behavior changes. The new strings are public configuration and MCP tool
metadata, not secrets.

## Constraints and decisions

- Maintain compatibility for manifests that omit both new fields.
- Since the default advertised MCP tool name changes from `invoke_agent` to
  the agent manifest's `name`, MCP clients that call the old name must update
  their tool selection. This is intentional to make multiple agents
  distinguishable; an explicit override can retain another chosen name.
- Preserve the existing `invoke_agent` argument schema and response contract.
- Keep the fields optional in the versioned schema and reject unknown fields
  as before.

## Acceptance criteria

1. A manifest without the new fields loads and its MCP tool uses the manifest
   `name` and `description`.
2. A manifest with one or both fields overrides only the values supplied.
3. The packaged schema accepts valid optional values and rejects invalid or
   blank values.
4. MCP list-tools tests prove the advertised name and description for default
   and override cases; invocation tests call the configured operation name and
   retain the current arguments and response behavior.
5. All delivered agent manifests validate against the updated schema.
6. Runtime Python configuration/MCP documentation and `ai_agents` configuration
   or hosting documentation describe the defaults and override fields.
7. Existing MCP authentication and conversation-scope tests continue to pass.

## Validation impact

- Runtime: manifest schema/input/loader tests, MCP endpoint contract tests, and
  documented Python lint and test gates for changed Python files.
- `ai_agents`: delivered-manifest schema checks, hosted Mail/Wiki MCP contract
  tests, the MCP inspection client tests if affected, and documented Ruff and
  pytest gates for changed Python files.
- Validate both repositories independently on their current feature branches.

## Risks and open questions

- The default tool-name change is externally visible to clients that currently
  invoke `invoke_agent`; tests and the inspection client need to use the tool
  name returned by MCP discovery.
- Before implementation, the plan must confirm the runtime hosting API path
  that carries manifest-specific operation metadata without changing unrelated
  discovery identity fields.
- No unresolved naming decision remains: use `mcp_agent_operation_name` and
  `mcp_agent_description` as the YAML keys.
