---

## applyTo: "**/*.py"

# Python Development Standards

## General

All production Python code must be:

* typed
* object-oriented for business logic
* testable
* readable
* maintainable
* compatible with SonarQube quality practices

Use Python 3.12+ features where appropriate.

---

## Classes

Business behavior should be encapsulated in cohesive classes.

Prefer composition over inheritance.

Classes should have:

* one clear responsibility
* explicit dependencies
* small public APIs

Avoid god classes.

---

## Dependency Injection

Inject dependencies through constructors.

Prefer:

```python
class JiraRiskAnalysisSkill:

    def __init__(
        self,
        jira_tools: JiraTools,
        risk_detector: RiskDetector,
    ) -> None:
        self._jira_tools = jira_tools
        self._risk_detector = risk_detector
```

Avoid constructing infrastructure dependencies inside business classes.

---

## Method Design

Methods should do one thing.

Use early returns.

Avoid:

* deep nesting
* long methods
* high cyclomatic complexity
* large conditional chains

When complexity grows, extract a cohesive responsibility into another class.

---

## Models

Prefer typed models.

Use dataclasses or an appropriate validation/modeling library consistently with the repository architecture.

Avoid passing loosely structured dictionaries between layers.

---

## Exceptions

Use explicit exceptions.

Never silently swallow exceptions.

Do not use broad exception handling without a recovery strategy.

---

## Naming

Names must describe business concepts.

Prefer:

```text
ProjectStatusAnalyzer
MailThreadAnalyzer
ActionExtractor
McpToolRegistry
```

Avoid generic names such as:

```text
Manager
Helper
Utils
Processor
Thing
```

unless the responsibility is genuinely clear from the name.

---

## Imports and Dependencies

Keep imports explicit.

Do not introduce a dependency solely to solve a trivial problem.

Avoid circular dependencies.

Respect architectural layer boundaries.

---

## Logging

Use structured logging through the repository logging abstraction.

Never log:

* passwords
* tokens
* authentication headers
* unnecessary email content
* secrets
* sensitive customer data

---

## Code Quality

Do not suppress SonarQube warnings without documented justification.

Prefer refactoring over suppression.
