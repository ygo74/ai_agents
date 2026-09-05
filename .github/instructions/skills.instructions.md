---

## applyTo: "src/skills/**/*.py"

# Skill Development Standards

A Skill represents a reusable domain capability.

Examples:

* MailThreadAnalysisSkill
* ActionExtractionSkill
* JiraRiskAnalysisSkill
* ProjectStatusAnalysisSkill
* DocumentSynthesisSkill

---

## Responsibilities

A Skill may:

* orchestrate multiple MCP tools
* transform retrieved information
* apply domain logic
* analyse data
* produce structured domain results

A Skill must NOT:

* implement direct system integrations
* contain framework-specific orchestration
* contain authentication code
* bypass authorization

---

## MCP interaction

Skills interact with systems through typed MCP tool abstractions.

Example:

```text
ProjectRiskAnalysisSkill
    |
    +-- JiraTools
    +-- ConfluenceTools
    +-- MailTools
    |
    +-- RiskDetector
```

---

## Reusability

Skills should be reusable across:

* multiple agents
* multiple scenarios
* multiple agentic frameworks

Do not duplicate a Skill for Microsoft Agent Framework, LangChain or CrewAI.

---

## Deterministic business logic

Where business logic can be deterministic, implement it deterministically.

Do not ask the LLM to perform calculations, filtering or simple rule-based decisions that can be implemented reliably in code.

Use LLM reasoning where it provides genuine value.

---

## Testability

Skills must be independently testable.

MCP dependencies should be injected and replaceable with mocks/fakes.
