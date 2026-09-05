---

## applyTo: "tests/**/*.py"

# Testing Standards

Tests are a first-class part of the architecture.

## Unit tests

Test business logic independently from:

* LLM providers
* MCP servers
* external systems
* network services

Use mocks/fakes through dependency injection.

---

## Integration tests

Integration tests verify:

```text
Agent
 -> Skill
 -> MCP Client
 -> MCP Server
```

Use controlled test systems or test fixtures.

Do not require production enterprise systems.

---

## Agent evaluation

Agent scenarios must be reproducible.

Each scenario should define:

* input
* available tools
* expected tool usage where applicable
* expected result characteristics
* security expectations
* evaluation criteria

---

## Security tests

Test at minimum where applicable:

* unauthorized access
* cross-user access
* prompt injection
* tool misuse
* confirmation bypass
* data leakage

---

## Framework comparison

The same scenarios should be executable against:

* Microsoft Agent Framework
* LangChain
* CrewAI

Keep scenario data and evaluation criteria framework-independent.
