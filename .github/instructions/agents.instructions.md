---
applyTo: "agents/**/*.py"
description: Route agent implementation guidance to repository-owned architecture rules and role references.
---

Follow the repository root `AGENTS.md` and `WORKFLOW.md`, then load the
Python implementation reference and the relevant Mail/Wiki specification
linked by the local workflow skill. Agents use framework APIs only at their
adapter boundary, call enterprise systems through MCP abstractions, and never
authorize protected operations themselves.
