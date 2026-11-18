---
name: implementation-plan
description: Analyze the existing agent architecture and prepare a Python implementation plan for an approved specification.
---

# Implementation plan

Use after the new or amended SPEC is approved. Read the
[tracking artifact templates](../development-workflow/references/artifact-templates.md)
and Python Solution Architect reference from `references/`; load only the
relevant agent (Mail, Wiki, Jira/tickets, user memory, or orchestration) and
framework specifications.
For a new agent, user-memory persistence, an orchestrator, or cross-agent
architecture, also read the shared
[agent-family architecture reference](references/agent-family-architecture.md).
Inspect current source, module dependencies, delivered configuration, tests,
docs, and examples before selecting changes.

Create a new `PLAN.md` for a new tracking folder or amend the existing branch's
PLAN in place. Keep previously completed work clear, add the new scope and
decisions as an amendment, and do not create another tracking folder for an
existing remote branch. Plan repository-scoped steps, reuse decisions,
dependencies, contracts and migration effects, test-first validation,
docs/examples, and completion criteria. Preserve framework independence above
adapters, MCP boundaries, deterministic authorization and confirmation, and
untrusted-content handling.
Prefer small, typed, cohesive classes, SOLID reuse, and early exits. Keep the
code straightforward for a junior developer to debug. Do not introduce an
abstraction unless the current system demonstrates the need.

Present the complete new or amended `PLAN.md`, affected areas, major decisions,
risks, and validation. Wait for explicit approval before creating or extending
tasks or changing implementation code.
