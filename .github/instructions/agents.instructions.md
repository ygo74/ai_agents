---

## applyTo: "src/agents/**/*.py"

# Agent Development Standards

An Agent is responsible for:

* understanding user intent
* deciding which capabilities/skills are appropriate
* orchestrating execution
* interacting with MCP tools through approved abstractions
* producing a structured response

An Agent is NOT responsible for implementing system integrations.

---

## Agent boundaries

An agent MUST NOT:

* call Exchange directly
* call Jira directly
* call Confluence directly
* call databases directly
* call enterprise APIs directly

Use MCP tools.

---

## Skills

Agents should delegate domain processing to Skills.

Prefer:

```text
Agent
  -> Skill
  -> MCP Tool
```

over putting all reasoning logic directly inside the Agent class.

---

## Framework independence

Do not put domain business logic into framework-specific Agent classes.

Framework adapters should primarily translate between:

* framework conventions
* repository Agent/Skill abstractions
* MCP tool interfaces

---

## Agent execution

Agent execution should be observable.

Important events should expose:

* agent name
* scenario
* user context identifier
* selected skill
* selected tools
* execution status
* latency
* errors

Never expose secrets.

---

## Side effects

Agents must not silently execute high-impact side effects.

WRITE operations must pass through the policy/confirmation mechanism.

---

## Output

Prefer structured outputs.

Responses should distinguish:

* facts
* analysis
* recommendations
* actions
* sources
* uncertainties
