---
name: implementation-plan
description: Analyze the existing Mail/Wiki architecture and prepare a Python implementation plan for an approved specification.
---

# Implementation plan

Use after SPEC approval. Read the [tracking artifact templates](../development-workflow/references/artifact-templates.md)
and Python Solution Architect reference from `references/`; load only the
relevant Mail/Wiki and framework specifications.
Inspect current source, module dependencies, delivered configuration, tests,
docs, and examples before selecting changes.

Plan repository-scoped steps, reuse decisions, dependencies, contracts and
migration effects, test-first validation, docs/examples, and completion
criteria. Preserve framework independence above adapters, MCP boundaries,
deterministic authorization and confirmation, and untrusted-content handling.
Prefer small, typed, cohesive classes, SOLID reuse, and early exits. Keep the
code straightforward for a junior developer to debug. Do not introduce an
abstraction unless the current system demonstrates the need.

Present `PLAN.md`, affected areas, major decisions, risks, and validation. Wait
for explicit approval before creating tasks or changing implementation code.
