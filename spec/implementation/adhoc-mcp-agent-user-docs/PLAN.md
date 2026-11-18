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

## Amendment plan: workflow tracking and branch routing

This amendment adds workflow guidance to the already completed documentation
request. The tracking folder remains canonical because the current branch
`feature/37-mcp-agent-endpoints` still has a matching `origin` ref in both
repositories. Do not create a second request folder. The tracking status was
checked independently: `ai_agents` at `100d9c2f` and
`ai-enterprise-agent-runtime` at `e2ca5637`; each local branch tracks the
matching remote branch.

### Repository scope

- In `ai_agents`, update `AGENTS.md`, `WORKFLOW.md`, and the skills that route
  work, create SPEC/PLAN artifacts, coordinate repositories, or run the three
  documentation/consolidation flows:
  `development-workflow`, `feature-specification`, `implementation-plan`,
  `implementation-tasks`, `multi-repo-coordination`, `user-docs`,
  `contributor-docs`, and `spec-consolidation`.
- Make the equivalent updates in `ai-enterprise-agent-runtime` so the two
  repositories use one English-language policy while keeping repository-specific
  paths and role guidance.
- Keep `ai_agents` as the canonical request record and record independent
  branch checks for the runtime repository in this journal.
- Do not change application code, generated user/contributor documentation,
  CI, or release behavior. Commit and push these workflow and tracking changes
  only after the maintainer explicitly requests delivery.

### Workflow decisions to encode

1. Classify the request before entering development tracking. For a request
   limited to user documentation, contributor documentation, or global spec
   consolidation, invoke the relevant skill directly without creating or
   updating request SPEC/PLAN files. Such repository changes still follow the
   branch decision below. Requests that also change implementation behavior
   follow full development tracking.
2. For each affected repository independently, inspect the current branch,
   working tree, and remote branch state before creating or reusing tracking:
   - On `main`, create a request branch from the latest fetched `origin/main`
     and start new SPEC/PLAN artifacts.
   - On a non-main branch present on `origin`, remain on that branch and update
     its existing canonical SPEC and PLAN in place.
   - On a non-main branch absent from `origin`, fetch `origin/main`, create a
     new request branch from that updated base, and start new SPEC/PLAN
     artifacts.
3. Never discard or silently overwrite local changes during branch selection.
   If a safe branch transition cannot be made, stop before editing and report
   the specific repository state.
4. Require SPEC approval before PLAN approval and PLAN approval before task or
   implementation changes. When updating an existing request, present the
   amended SPEC and PLAN at the same gates.
5. After an amended PLAN is approved, extend its existing TASKS checklist and
   JOURNAL; do not create a competing request history.

### Implementation sequence and review

1. Update both repositories' `AGENTS.md` and `WORKFLOW.md` to agree with their
   workflow skills and distinguish new requests from continuing remote-branch
   work.
2. Update the eight listed skills in both repositories. Make the development
   workflow the routing point, put branch/tracking selection in the
   specification and coordination guidance, and state the documentation-only
   bypass explicitly in its entry point and each applicable documentation or
   consolidation skill.
3. Review all changed instructions together for contradictions, consistent
   English wording, valid relative links, origin/main refresh behavior, and
   independent multi-repository decisions. Record actual review in the journal.

### Completion criteria and validation

- Both repositories state matching request classification and branch rules.
- No skill creates a fresh tracking folder when continuing a branch that still
  exists on origin; it directs agents to update that branch's existing SPEC and
  PLAN.
- Deleted remote branches are based on fetched `origin/main`, with local work
  protected.
- Documentation-only and consolidation-only work skips development SPEC/PLAN
  tracking, while mixed implementation work retains both approval gates.
- AGENTS, WORKFLOW, and all affected skills agree; links and changed Markdown
  are reviewed. No tests are needed because this amendment changes instructions
  only. Delivery requires an explicit maintainer request.
