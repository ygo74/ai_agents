---
name: test-driven-implementation
description: Implement approved agent tasks with focused tests, repository architecture, and Solution Architect review of scope follow-ups.
---

# Test-driven implementation

Follow the approved SPEC, PLAN, and TASKS. Load the Python implementation
reference under `references/` and only the behavior pages relevant to the
affected agent (Mail, Wiki, Jira/tickets, user memory, or orchestration) and
framework.
For a new agent or cross-agent change, also load the shared
[agent-family architecture reference](../implementation-plan/references/agent-family-architecture.md).
Inspect callers, tests, and existing adapters before changing code; record what
was considered for reuse.

For behavior changes, write a failing focused test, make the smallest passing
change, and refactor while the relevant checks remain green. Keep typed domain
objects and deterministic policies in application layers; keep framework APIs
at adapters; use MCP ports for external systems. Avoid duplicate runtime APIs
and speculative abstractions. Keep code and test fixtures clear enough for a
junior developer to debug.

Update task status and the primary repository's `JOURNAL.md` with decisions,
actual checks and results, and deviations. Send discovered improvements with
evidence to the Solution Architect for an in-scope or follow-up decision. Do not
expand approved scope silently.

Present implementation and validation for user review. After acceptance, invoke
consolidation, documentation, and image version skills only when requested or
included in the approved plan.
