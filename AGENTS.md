# Repository guidance

These instructions apply throughout this repository. Start from the current
system description in [`spec/README.md`](spec/README.md), then follow only the
architecture and relevant agent behavior pages (Mail, Wiki, Jira/tickets,
user memory, or orchestration) needed for the request. Approved
request work is tracked under `spec/implementation/` in the primary repository;
these records are for developers and agents, not user documentation.

## Architecture and engineering principles

- Keep business capabilities and security decisions independent of the agent
  framework. Mail uses Microsoft Agent Framework; Wiki uses LangChain/LangGraph.
- Agent skills own domain orchestration and deterministic business behavior.
  Framework adapters translate tool and session contracts. MCP is the boundary
  to enterprise systems; never call Exchange, Gmail, Confluence, Jira, databases,
  or enterprise APIs directly from an agent or skill.
- Use Clean Architecture / Onion Architecture with dependencies directed
  inward: domain policy, application use cases, infrastructure and framework
  adapters, then a composition root. New agents follow the common layer layout
  in the [agent architecture reference](.agents/skills/implementation-plan/references/agent-family-architecture.md);
  do not force unrelated Mail/Wiki migrations into a feature change.
- The shared `ai-enterprise-agent-runtime` library owns generic hosting,
  identity, contracts, security primitives, and MCP mechanics; do not recreate
  its public APIs here.
- Use typed domain models, enums for finite choices, focused classes and
  explicit ports. Inject replaceable collaborators through constructors and
  wire concrete adapters in bootstrap; avoid service locators and hidden
  globals. In Python, each concrete adapter explicitly subclasses the
  `Protocol` it implements. Follow DRY/SOLID and early exits; use cohesive
  classes to make responsibilities clear. Prefer a direct, small solution over
  speculative abstractions. Keep code understandable and debuggable by a
  junior developer.
- Make authorization, operation risk, and confirmation deterministic. A model
  can propose an action but cannot grant permission or confirm it. Content
  retrieved from enterprise systems or user memory is untrusted data and must
  remain fenced from instructions.
- Keep credentials in infrastructure; never put secrets or sensitive message
  and page content in prompts, logs, or audit events.
- Emit structured, traceable execution outcomes using safe identifiers and
  status/error fields. Return structured results that distinguish sourced
  facts, analysis, recommendations, actions, and uncertainty.
- Keep deterministic filtering, validation, date calculations, and authorization
  in code. Inject replaceable MCP ports so capabilities remain independently
  testable without a network.
- Use deterministic in-memory adapters and fakes for tests. Keep framework
  dependencies isolated by distribution and preserve the architecture tests.
- Design retained state for development and production: place state access
  behind an injected port, provide an in-memory development/test adapter, and
  configure a PostgreSQL or Redis production adapter whenever application
  state is retained beyond one operation. Choose by durability, query, and
  concurrency needs; define user partitioning, retention, and deletion. Treat
  bounded process-local caches separately and document their limits.
- Document every class and method so a developer can understand its purpose
  and arguments (Python docstrings; use the repository's standard documentation
  form for other languages). In each non-trivial method, add concise comments
  in the body to explain the algorithm's stages, ordering, and invariants; do
  not narrate obvious statements.
- Keep user and contributor documentation aligned with behavior; start at
  `doc/users/README.md`, `doc/contributors/README.md`, and `spec/README.md`.

## Workflow skills

- [`development-workflow`](.agents/skills/development-workflow/SKILL.md) routes
  ad hoc and Issue-linked requests through the approval gates.
- [`feature-specification`](.agents/skills/feature-specification/SKILL.md)
  selects Business Analyst or Solution Architect guidance by request outcome.
- [`implementation-plan`](.agents/skills/implementation-plan/SKILL.md) analyzes
  the current architecture and prepares a Python plan.
- [`implementation-tasks`](.agents/skills/implementation-tasks/SKILL.md)
  produces the ordered implementation checklist after plan approval.
- [`test-driven-implementation`](.agents/skills/test-driven-implementation/SKILL.md)
  implements approved tasks and records scoped follow-ups.
- [`multi-repo-coordination`](.agents/skills/multi-repo-coordination/SKILL.md),
  [`spec-consolidation`](.agents/skills/spec-consolidation/SKILL.md), and
  [`repository-delivery`](.agents/skills/repository-delivery/SKILL.md) apply
  when the request needs those phases.
- Existing documentation, code-review, and image-version skills remain under
  `.agents/skills/` and are used when requested or included in approved scope.

Copilot instruction files may route to these repository rules; they must not
define a competing workflow.
