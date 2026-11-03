# Python Solution Architect — ai_agents

Load for technical plans affecting Mail, Wiki, framework adapters, hosting,
configuration, or shared runtime integration.

## Ownership and boundaries

- Mail owns its domain models, permission names, untrusted origins, operation
  catalogue, security floor, application skills, tool ports, MCP dialects,
  confirmation meaning, and composition. Its framework adapter uses the GA
  Microsoft Agent Framework APIs.
- Wiki owns its graph, skills, capability filtering, permissions, confirmation
  tickets, MCP dialects, and composition. It uses public LangChain/LangGraph
  APIs.
- Keep generic identity, hosting, contracts, security primitives, and MCP
  transport mechanics in `ai-enterprise-agent-runtime`. Use its public APIs;
  do not add compatibility aliases or copy its implementation.
- MCP is the only boundary to enterprise systems. Do not place direct Gmail,
  Exchange, Confluence, Jira, database, or HTTP integration in an agent or
  capability skill.
- Keep domain/application code framework-independent. Framework adapters
  translate skill descriptors and session state; they do not own business
  policy.

## Design and validation

- Preserve layer direction and package boundaries. Respect Mail's layered
  domain/application/infrastructure/adapters/bootstrap structure and Wiki's
  current module layout; do not force a broad rewrite for symmetry.
- Use typed Pydantic/domain models, focused protocols, enums, and constructor
  injection. Keep deterministic policy in code, avoid raw maps for domain data,
  and prefer a small direct design over speculative abstractions.
- Preserve caller scoping, one-use confirmations, security floors, prompt
  fences for untrusted data, and identifier-only auditing.
- Preserve isolated agent/framework distributions and the mock compositions.
  Use the repository's architecture, contract, unit, integration, security,
  and agent tests that are relevant to the approved change.
- Update delivered `AGENT.md`, `SKILL.md`, and YAML manifests only when their
  behavior or contracts change. Keep user and contributor guides in sync.
