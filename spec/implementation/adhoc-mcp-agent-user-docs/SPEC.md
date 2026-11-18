# Specification

## Request source and repositories

- Source: ad hoc request from the repository maintainer; no Issue was requested.
- Primary repository: `ai_agents`, which operates the Mail and Wiki hosted MCP
  agent endpoints.
- Secondary repository: `ai-enterprise-agent-runtime`, which owns the generic
  agent MCP hosting contract and its shared user guide.
- Keep the two repositories' branches and Git histories separate. This is the
  canonical request record in `ai_agents`.

## Objective and current context

The maintainer verified that the Mail and Wiki MCP endpoints work and wants the
user documentation in both repositories ready before merging. Existing guides
describe the `/mcp` endpoint, authentication, the conversational tool metadata,
and the `message` and `conversation_id` arguments. They do not provide a
complete, copyable MCP discovery and invocation exchange in the agent hosting
guides, so a user must infer how to inspect and call the advertised tool.

## Scope and exclusions

- In `ai_agents`, update the Mail and Wiki HTTP user guides with concise,
  language-neutral MCP JSON-RPC examples showing `tools/list` followed by
  `tools/call` using the tool name returned by discovery.
- In those guides, explain the actual defaults and independent manifest
  overrides for the hosted operation name and description, the required
  `message` argument, optional `conversation_id`, and that the same endpoint
  authentication protects MCP requests.
- In `ai-enterprise-agent-runtime`, update the generic MCP hosting user guide
  with equivalent discovery and invocation examples, including the fact that
  callers should use the operation name returned by `tools/list`.
- Keep examples neutral to programming language and use placeholders for
  credentials and agent-specific operation metadata.
- Preserve existing page structure and indexes; no new page is needed.
- Do not change runtime or agent behavior, schemas, samples, contributor docs,
  consolidated specifications, scripts, tests, CI, or release configuration.
- Do not commit, push, or merge either repository as part of this request.

## Expected user behavior

A user can follow the relevant guide to discover an agent's advertised MCP
operation and its description and input schema, then call that operation with a
message and optional conversation identifier. The examples make clear that
operation names may differ between agents or be customized in the YAML
manifest, so a client should not assume a fixed name.

## Architecture, permissions, and data

This is documentation-only. MCP authentication and authorization remain
enforced by the hosted endpoint. Examples contain no credentials or private
data and do not encourage unauthenticated calls.

## Constraints and decisions

- Follow each repository's user-documentation skill; shared user guides use
  simple English and language-neutral HTTP/JSON examples.
- Verify request fields and metadata behavior against the checked-in runtime,
  agent manifests, tests, and existing guides.
- Existing docs already explain the MCP endpoint and metadata defaults; the
  changes should add an actionable protocol example without duplicating the
  full contributor-oriented MCP inspection utility instructions.

## Acceptance criteria

1. The Mail and Wiki HTTP user guides each show discovery and invocation against
   their `/mcp` endpoint using the discovered operation name.
2. The guides accurately document operation metadata defaults and independent
   overrides, input arguments, authentication, and conversation continuity.
3. The runtime MCP hosting guide shows generic `tools/list` and `tools/call`
   JSON-RPC examples consistent with the runtime contract.
4. Examples contain only placeholder credentials and valid JSON-RPC shapes.
5. Existing links and documentation indexes remain valid; no behavior or
   non-documentation files change.

## Validation impact

- Review rendered Markdown, JSON snippets, repository-relative links, and the
  documented names against implementation and configuration.
- Do not run automated tests solely for this documentation change.

## Risks and open questions

- MCP SDKs may display structured tool results differently. Examples should
  describe the stable JSON-RPC request and the semantic result without claiming
  a client-specific presentation.
- None open at specification time.

## Amendment: reuse request tracking and route documentation-only work

The maintainer reports that the current workflow creates a new SPEC for every
change request. Amend this request to update the workflow guidance in both
repositories so work on an existing remote branch updates that branch's
existing request SPEC and PLAN. A new request SPEC and PLAN are created only
when the branch decision calls for a new work branch.

Before creating or reusing request tracking, inspect the current branch and
whether that branch exists on `origin`, independently for each affected
repository:

- On `main`, create a request branch from the latest `origin/main` and create a
  new request SPEC and PLAN.
- On a non-main branch that still exists on `origin`, stay on that branch and
  update its existing canonical SPEC and PLAN in place.
- On a non-main branch absent from `origin`, fetch the latest `origin/main`,
  create a new request branch from it, and create a new SPEC and PLAN. Preserve
  local changes and never discard them as part of branch selection.

Requests limited to user documentation, contributor documentation, or
consolidating the global repository specification use the relevant skill
directly and do not create or update development request SPEC/PLAN artifacts.
The branch decision still applies to repository changes. If a request also
changes implementation behavior, it uses the normal SPEC/PLAN workflow.

### Amendment acceptance criteria

1. Both repositories describe the same branch and tracking decision rules,
   including checking origin independently for every repository.
2. Existing request tracking on a branch that remains on origin is updated in
   place; a new tracking folder is not created for that case.
3. A deleted remote branch leads to a new branch based on fetched `origin/main`
   and new request tracking, while preserving local work.
4. User-doc, contributor-doc, and spec-consolidation-only requests bypass
   development SPEC/PLAN tracking; implementation requests do not.
