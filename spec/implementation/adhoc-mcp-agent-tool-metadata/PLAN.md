# Implementation Plan

## Approved SPEC

Implement the approved
[`SPEC.md`](SPEC.md): expose agent-specific MCP tool metadata by default and
allow independent optional YAML overrides. `ai_agents` is the primary
repository; `ai-enterprise-agent-runtime` owns the shared manifest and MCP
hosting APIs.

## Existing architecture and reuse analysis

- The runtime loads `agent.yaml` through `AgentManifestInput`, validates it
  against the packaged `agent.schema.json`, and creates an `AgentManifest`.
- Mail and Wiki already derive their discovery `AgentDescriptor` from that
  manifest. Its `display_name` and `description` therefore already provide the
  requested defaults.
- `McpAgentEndpoint` currently ignores that metadata when registering the
  MCP tool and hard-codes `invoke_agent` plus a generic description.
- Both agent HTTP services use `ManagedAgentWorker` with `AgentDefinition`,
  which passes the descriptor to `HostingFactory`. The descriptor is explicitly
  provider-neutral and must remain free of MCP transport settings.
- Reuse this existing path. Carry optional MCP operation overrides separately
  through `AgentManifest` → `AgentDefinition` → `ManagedAgentWorker` →
  `HostingFactory` → `McpAgentEndpoint`. The MCP endpoint falls back to the
  descriptor's display name and description when overrides are absent. Direct
  `HostingFactory` users can continue to rely on descriptor defaults and may
  supply the same optional overrides through `add_agent`.
- Do not add a second capability catalog, enumerate internal skills in the
  tool description, or change descriptor discovery behavior. The manifest
  description remains the curated routing summary; one conversational MCP
  operation continues to invoke the agent.

## Repository and component scope

### `ai-enterprise-agent-runtime` (secondary, implement first)

- Add optional `mcp_agent_operation_name` and `mcp_agent_description` to the
  typed YAML input and resolved `AgentManifest`; preserve them in the loader.
- Add optional fields to the packaged agent JSON Schema as non-empty strings.
  Keep the existing schema identifier because these optional fields extend the
  accepted shape without invalidating existing manifests.
- Add optional MCP operation metadata to `AgentDefinition` and keyword-only
  override arguments to `HostingFactory.add_agent`.
- Pass metadata from `ManagedAgentWorker` into the hosting factory. Resolve
  defaults in `McpAgentEndpoint` from `AgentDescriptor.display_name` and
  `AgentDescriptor.description`; validate the resolved MCP name and
  description before server registration.
- Keep MCP server identity/instructions, discovery descriptor, authentication,
  request arguments, and response behavior unchanged.
- Update runtime manifest/MCP documentation and runnable MCP hosting example.

### `ai_agents` (primary)

- Pass the manifest's optional override fields into each Mail/Wiki
  `AgentDefinition`; leave current manifests without overrides to exercise the
  default behavior.
- Update MCP service contract tests to assert Mail/Wiki-specific operation
  names and descriptions and continue invoking the operation advertised by
  MCP discovery. Keep the MCP inspector generic and listing-based.
- Update agent configuration and hosted-MCP documentation with defaults,
  override keys, and the client-visible operation-name change.

## Ordered steps and dependencies

1. **Runtime regression tests:** add failing manifest input/loader and JSON
   Schema tests for omitted, present, and blank values; add failing MCP endpoint
   tests for descriptor defaults and independent override behavior.
2. **Runtime implementation:** add typed manifest fields and loader mapping;
   update packaged JSON Schema; carry optional metadata through
   `AgentDefinition`, `ManagedAgentWorker`, and `HostingFactory`; register the
   configured MCP tool name and description, falling back to descriptor values.
3. **Runtime validation and docs:** run the focused runtime tests, then the
   repository's documented Python lint and test gates. Update manifest/MCP
   docs and the MCP hosting sample.
4. **Agent contract tests:** update failing Mail/Wiki MCP tests and support
   helpers to use the operation names returned by MCP; assert the manifest
   descriptions appear in tool listings.
5. **Agent integration:** pass optional manifest overrides into both agent
   definitions, retaining default behavior for the delivered Mail and Wiki
   manifests. Update configuration and hosted-MCP documentation.
6. **Agent validation:** validate every delivered manifest, run the focused
   Mail/Wiki hosted-MCP tests, then run documented Ruff and pytest gates for
   this repository.
7. Record actual checks and outcomes in the canonical journal and present the
   two repository diffs for user review. Keep commits, branches, and histories
   separate; this plan does not include push, merge, release, or CI changes.

## Test-first validation

- Runtime tests cover `AgentManifestInput`, `AgentManifestLoader`, packaged
  schema acceptance/rejection, MCP tool listing, custom name/description
  overrides, and unchanged tool arguments/identity context.
- Agent tests cover schema validation of delivered manifests, expected tool
  metadata on Mail and Wiki MCP endpoints, and calls by the advertised name.
- Test the default values and each override independently so one custom field
  does not erase the other manifest-derived default.
- Run Python lint and pytest according to each repository's local delivery
  skill. Run the relevant focused checks first; report only commands actually
  executed and their results.

## Security and deployment impact

No identity, authorization, confirmation, conversation partitioning, or
enterprise-system access rules change. Tool metadata is non-secret public
configuration. Existing manifests remain valid. The advertised tool name
changes from `invoke_agent` to the manifest agent name by default; deployments
that require a stable old name can set `mcp_agent_operation_name: invoke_agent`.
Update bundled tests and client guidance to select names returned by MCP tool
discovery. Do not change authentication settings, CI runtime pins, package
release versions, or deployment topology.

## Documentation and examples

- Runtime: Python agent-manifest and MCP endpoint guides, plus the MCP hosting
  example.
- `ai_agents`: configuration reference and Mail/Wiki hosted MCP user guides.
- State that `mcp_agent_operation_name` and `mcp_agent_description` are
  optional top-level `agent.yaml` keys and each overrides independently.

## Risks and completion criteria

- MCP clients that hard-code `invoke_agent` will need to select the new
  advertised name or configure the old name as an override.
- The override values must not leak into unrelated discovery identity fields.
- Both repositories are complete when default and override behavior pass the
  focused tests, local Python quality gates pass, docs/examples describe the
  public behavior, and the separate repository diffs are ready for user review.
- No implementation begins until this PLAN is explicitly approved.
