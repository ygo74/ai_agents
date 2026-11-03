# Python Implementation Expert — ai_agents

- Follow the Python version, dependency groups, formatter, strict type checks,
  and test commands defined by the affected distribution.
- Preserve the existing Mail or Wiki domain/application boundaries. Use typed
  domain and Pydantic models, protocols for tool ports, enums for finite values,
  and explicit dependency injection.
- Use Microsoft Agent Framework only in the Mail adapter and LangChain/LangGraph
  only in the Wiki adapter. Keep business capabilities framework independent
  and use runtime public APIs for generic hosting and MCP behavior.
- Never call an enterprise API directly. Keep secrets in infrastructure,
  retrieved content fenced as untrusted data, and write authorization and
  confirmation deterministic.
- Prefer existing classes and fixtures, early exits, small responsibilities,
  and direct control flow. Keep error paths and tests understandable to a junior
  developer.
