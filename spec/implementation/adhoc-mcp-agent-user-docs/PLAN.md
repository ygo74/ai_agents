# Implementation Plan

## Approved SPEC

Approved specification: [SPEC.md](SPEC.md). This is a documentation-only
change covering MCP consumers of the Mail and Wiki agents and the generic
managed-agent MCP hosting guide.

## Existing architecture and reuse analysis

- `ai_agents/doc/users/mail-agent-http.md` and
  `ai_agents/doc/users/wiki-agent-http.md` already describe the `/mcp` route,
  authentication, the single conversational tool, the optional manifest
  overrides, and conversation affinity. Extend their existing MCP sections;
  do not add another page or duplicate the full developer inspector workflow.
- The delivered Mail manifest defaults to `name: mail-agent` and the Mail
  description; the Wiki manifest defaults to `name: wiki-agent` and the Wiki
  description. Both currently omit the optional MCP metadata overrides.
- Mail's hosted MCP endpoint uses the configured JWT policy; its guide already
  documents the bearer credential and public MCP resource URL. Wiki's checked-in
  endpoint uses `X-API-Key`; its guide already documents that header.
- `ai-enterprise-agent-runtime/doc/users/mcp-server-hosting.md` already has a
  protected `tools/list` request and describes the agent metadata defaults,
  overrides, and argument names. Extend this page with the corresponding
  `tools/call` request and the discovery response fields users need to select
  the operation.
- The generic endpoint registers a structured conversational tool with
  required `message`, optional `conversation_id` defaulting to `default`, and
  response fields `status`, `conversation_id`, `output`, and `metadata`. Tool
  identity defaults to the agent descriptor metadata unless independently
  overridden in the manifest.

## Repository and component scope

1. **Primary — `ai_agents`**, branch
   `feature/37-mcp-agent-endpoints`:
   - Update `doc/users/mail-agent-http.md` with `tools/list` and `tools/call`
     examples using Mail's bearer authentication.
   - Update `doc/users/wiki-agent-http.md` with equivalent examples using the
     checked-in `X-API-Key` authentication.
   - Show that clients select the discovered tool name, that `message` is
     required, and that an optional `conversation_id` continues a conversation.
     Retain the existing explanation of metadata defaults, overrides,
     authorization identity, and session affinity.
2. **Secondary — `ai-enterprise-agent-runtime`**, branch
   `feature/37-mcp-agent-endpoints` in its independent history:
   - Update `doc/users/mcp-server-hosting.md` with a generic `tools/call`
     request corresponding to its existing `tools/list` example.
   - Illustrate the advertised tool metadata and the invocation arguments with
     placeholders, and describe the structured result without prescribing how
     a specific MCP client renders it.

Examples use language-neutral HTTP/JSON blocks, placeholder credentials, the
existing `/mcp` route, and standard JSON-RPC method names. They do not assume a
fixed operation name; the operation name from discovery is reused in the call.
No README index changes are needed because no pages are added.

## Ordered steps and dependencies

1. Update the Mail and Wiki MCP sections in `ai_agents` using the authentication
   headers and metadata from their current manifests and runtime behavior.
2. Update the runtime's generic MCP hosting page to pair discovery with
   invocation and explain the input and structured result contract.
3. Review both repositories' diffs independently for accurate links, valid
   JSON-RPC shapes, consistent English, placeholder-only credentials, and
   agreement with their source/configuration. Record actual review results in
   the canonical journal.

The documentation changes are independent after this plan is approved. Keep
all edits within the repository that owns each guide and preserve each branch's
Git history.

## Test-first validation

This request changes no runtime behavior, schemas, or executable examples, so
no tests are needed. Validate the written material by checking each HTTP
request, JSON body, metadata name, authentication header, argument, relative
link, and result description against the current source, manifests, and
existing tests. Do not add or run automated tests solely for this documentation
change.

## Security and deployment impact

No service, identity, authorization, network, or state behavior changes.
Documentation requests continue to show protected access and placeholder
credentials. Mail and Wiki retain the current authentication policies and
process-local conversation behavior already documented on their pages.

## Documentation and examples

The three existing user-facing guides are the complete scope. Keep shared
runtime examples language-neutral and use the repository's simple-English user
documentation style. Do not change contributor documentation, tracking
material outside this canonical request, or consolidated system
specifications.

## Risks and completion criteria

- A hardcoded operation name could mislead users when a manifest override is
  present. The examples must show that `tools/call` uses the name returned by
  `tools/list`.
- MCP clients may present structured tool results differently. Document the
  stable response data without promising a client-specific display.
- Complete when all three guides show a coherent protected discovery and
  invocation path, their claims agree with the current implementation, links
  remain valid, and only the approved documentation files plus canonical
  tracking artifacts are changed.
