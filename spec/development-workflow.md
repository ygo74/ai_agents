# Development workflow and architecture principles

This page describes the repository-local workflow for changing Mail, Wiki, and
their framework integrations. Start new requests from the current system
specification in [`README.md`](README.md) and only the domain pages relevant to
the request. Request records under `spec/implementation/` in the primary
repository are developer and agent tracking material, not product or user
documentation.

## Request lifecycle

The workflow skills live in [`.agents/skills/`](../.agents/skills/). Use
`development-workflow` to route an ad hoc request or an optional Issue through
these phases:

| Phase | Skill | Result |
|---|---|---|
| Specify | `feature-specification` | `SPEC.md` written with Business Analyst or Python Solution Architect guidance. |
| Plan | `implementation-plan` | Existing code, architecture, tests, configuration, and docs analyzed; `PLAN.md` presented. |
| Break down | `implementation-tasks` | Ordered repository-scoped `TASKS.md` after PLAN approval. |
| Implement | `test-driven-implementation` | Test-first changes and progress captured in the canonical journal. |
| Coordinate | `multi-repo-coordination` | Separate branches and changes when `ai-enterprise-agent-runtime` is also affected. |
| Consolidate and deliver | `spec-consolidation`, `repository-delivery` | Verified system behavior and reviewed repository changes when in scope. |

SPEC and PLAN each require explicit user approval. TASKS has no additional
approval gate. Behavior changes use a failing test, the smallest passing
implementation, then refactoring with relevant checks still passing. Update
task status and record decisions, actual validations, and deviations in
`JOURNAL.md`. Ask the Solution Architect to classify any discovered improvement
as in-scope or a separate user proposal.

The canonical request folder is
`spec/implementation/<issue-N-or-adhoc-slug>/` in the primary repository, with
`SPEC.md`, `PLAN.md`, `TASKS.md`, and `JOURNAL.md`. A new request starts from
this consolidated system specification, not an older tracking record. Keep Git
histories, branches, validations, commits, and pull requests separate per
repository.

## Role selection

For the SPEC, load one role based on the main outcome:

- **Business Analyst** for primarily functional Mail/Wiki agent capabilities.
  Capture user goals, workflows, expected outcomes, acceptance criteria, and
  safety requirements without prescribing code structure.
- **Python Solution Architect** for technical changes such as shared runtime
  behavior, framework integration, hosting, contracts, configuration, or
  architecture.

For the PLAN and task breakdown, always load the Python Solution Architect
reference. For implementation, load the Python implementation-expert reference
and only the Mail, Wiki, or framework details needed by the request.

## Architecture and implementation principles

- Mail business behavior and permission meaning stay in the Mail domain and
  application. Mail's framework adapter uses Microsoft Agent Framework's GA
  APIs.
- Wiki owns its graph, permission policy, capability filtering, confirmation
  tickets, and MCP dialect; it uses LangChain/LangGraph.
- Keep capabilities framework-independent and put framework session/tool
  translation in adapters. Use the public `ai-enterprise-agent-runtime` APIs
  for shared identity, hosting, contracts, security primitives, and MCP
  mechanics; do not duplicate those APIs.
- MCP is the only integration boundary to enterprise systems. Agents and
  capability skills do not call Gmail, Exchange, Confluence, Jira, databases,
  or enterprise APIs directly.
- Use typed domain models, focused protocols, enums, and explicit dependency
  injection. Prefer DRY, SOLID, early exits, cohesive classes, and simple
  implementations a junior developer can understand and debug. Avoid
  speculative abstractions and framework wrappers.
- Keep authorization and confirmation deterministic. A model can propose a
  write but cannot authorize it. Fence retrieved Mail/Wiki content as untrusted
  data before reasoning. Keep secrets and sensitive content out of prompts,
  logs, traces, and audit events.
- Preserve caller-scoped sessions and tickets, one-use confirmations,
  fail-closed security floors, and deterministic mock adapters. Keep framework
  distributions isolated and maintain architecture tests.
- Use unit, contract, integration, security, and architecture tests that match
  the approved change; use injected fakes instead of live services.

## Post-acceptance work

After user acceptance, run consolidated spec, user documentation, contributor
documentation, and review skills when requested or included in the approved
plan. Use `image-version-bump` to prepare a tag-based release recommendation;
this repository has no package version manifest. Creating or pushing a `v*`
tag triggers image builds and GHCR publication and requires explicit user
authorization. Never merge or publish implicitly.
