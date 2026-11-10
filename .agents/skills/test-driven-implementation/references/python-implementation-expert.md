# Python Implementation Expert — ai_agents

- Follow the Python version, dependency groups, formatter, strict type checks,
  and test commands defined by the affected distribution.
- Preserve existing Mail/Wiki boundaries and follow the shared layer structure
  for new agents. Use typed domain and Pydantic models, protocols for tool
  ports, enums for finite values, and explicit dependency injection.
- For new agents, follow the common layer and directory structure in the
  [agent-family architecture reference](../../implementation-plan/references/agent-family-architecture.md).
  Keep framework calls in adapters and inject ports from bootstrap. Every
  concrete Python class implementing a Protocol explicitly subclasses it.
- When retaining application state beyond one operation, implement an
  in-memory adapter for development and tests plus a PostgreSQL or Redis
  production adapter selected by configuration.
- Use Microsoft Agent Framework only in the Mail adapter and LangChain/LangGraph
  only in the Wiki adapter. Keep business capabilities framework independent
  and use runtime public APIs for generic hosting and MCP behavior.
- Never call an enterprise API directly. Keep secrets in infrastructure,
  retrieved content fenced as untrusted data, and write authorization and
  confirmation deterministic.
- Prefer existing classes and fixtures, early exits, small responsibilities,
  and direct control flow. Keep error paths and tests understandable to a junior
  developer.
- Document every class and method with its purpose and arguments. For each
  non-trivial method, explain the algorithm inside its body with concise
  comments about stages, ordering, and invariants. Do not add line-by-line
  comments that merely repeat code.
