# Repository Development Workflow

`AGENTS.md` is the always-loaded source for agent architecture, security, and
engineering principles. Start each request from the consolidated behavior in
[`spec/README.md`](spec/README.md), then load only the relevant agent (Mail,
Wiki, Jira/tickets, user memory, or orchestration) and framework references.
Keep request records under `spec/implementation/` in the primary repository;
these records are for developers and agents, not user documentation.

## Request lifecycle

```text
user request or optional Issue
  → SPEC → user approval → PLAN → user approval → TASKS
  → test-driven implementation → review and user acceptance
  → requested documentation, consolidation, and release work
```

Use [`development-workflow`](.agents/skills/development-workflow/SKILL.md) as
the entry point. An Issue is optional; do not create one unless the user asks.

For a primarily functional capability of any agent, the specification skill
loads the Business Analyst reference. For a primarily technical request, it
loads the Python Solution Architect reference. The SPEC records the request,
scope, expected behavior, acceptance criteria, constraints, risks, and open
decisions. Present it and wait for explicit user approval before planning.

After SPEC approval, the planning skill examines the current source, tests,
contracts, configuration, documentation, and examples. It loads the Python
Solution Architect reference and, for new agents or cross-agent changes, the
shared [agent-family architecture reference](.agents/skills/implementation-plan/references/agent-family-architecture.md).
Present the PLAN and wait for approval. After plan approval, the architect
creates ordered `TASKS.md`; there is no additional task-approval gate.

Implement approved tasks test-first: failing test, minimal change, passing
test, and refactor for behavior changes. Keep the implementation simple, typed,
and understandable to a junior developer. Update task status and the canonical
journal as work proceeds. Ask the Solution Architect to classify discovered
improvements as in-scope or a separate user proposal.

## Engineering constitution

- Apply Clean Architecture / Onion Architecture to every agent. Dependencies
  point inward from framework, transport, and persistence adapters toward
  application ports and domain policy. Bootstrap is the composition root.
- New agents use the common layers and package structure in the
  [agent-family architecture reference](.agents/skills/implementation-plan/references/agent-family-architecture.md).
  Keep framework-specific code inside adapters. Mail and Wiki retain their
  current layouts until a scoped migration is approved.
- Mail owns its domain models, permissions, security floor, deterministic
  services, and application skills; its framework adapter uses Microsoft
  Agent Framework. Wiki owns its graph, capability filtering, and confirmation
  policy; it uses LangChain/LangGraph.
- Future Jira/ticket, user-memory, and orchestrator agents follow the same
  layers and contracts. Keep Jira access behind MCP, user memory partitioned by
  caller, and orchestration dependent on injected public agent contracts rather
  than other agents' private framework code.
- Use the public `ai-enterprise-agent-runtime` APIs for generic hosting,
  identity, contracts, security primitives, and MCP mechanics. Do not recreate
  those APIs or call enterprise systems directly from an agent or skill.
- Inject replaceable collaborators through constructors and compose concrete
  implementations in bootstrap. Every Python adapter explicitly subclasses the
  `Protocol` it implements. Keep framework distributions isolated and preserve
  deterministic mock compositions and architecture tests.
- For application state retained beyond one operation, define a storage port,
  an in-memory development/test adapter, and a PostgreSQL or Redis production
  adapter selected by configuration. Define caller partitioning, concurrency,
  retention, migration, and deletion behavior. Document the limits of any
  deliberately process-local cache.
- Document every class and method, including its purpose and arguments. In each
  non-trivial method body, add concise comments explaining the algorithm's
  stages, ordering, and invariants. Avoid comments that merely repeat code.

## Tracking and completion

Keep one canonical request folder in the primary repository:

```text
spec/implementation/<issue-N-or-adhoc-slug>/{SPEC,PLAN,TASKS,JOURNAL}.md
```

Start each new request from the consolidated `spec/` pages, not an old request
record. Keep tracking material out of user-facing documentation. After user
acceptance, use consolidation, user-documentation, contributor-documentation,
and image-version skills only when requested or included in the approved plan.
Pushing a `v*` tag triggers image publication and requires explicit user
authorization. Never merge or publish implicitly.
