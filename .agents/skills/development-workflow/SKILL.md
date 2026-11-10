---
name: development-workflow
description: Route ad hoc or Issue-linked changes through approved specifications, architecture plans, implementation tasks, and test-driven delivery.
---

# Development workflow

Start with the user request and current `spec/README.md`. An Issue may be
linked, but is optional and must never be created unless requested.

1. Identify the primary repository and any secondary repository. Read local
   `AGENTS.md`, `WORKFLOW.md`, and only the relevant consolidated pages.
2. Use [feature-specification](../feature-specification/SKILL.md) to create the
   canonical request `SPEC.md`. Present it and wait for explicit approval.
3. After approval, use [implementation-plan](../implementation-plan/SKILL.md)
   to inspect the current architecture and write `PLAN.md`. Present it and wait
   for explicit approval.
4. After plan approval, use [implementation-tasks](../implementation-tasks/SKILL.md)
   to write ordered `TASKS.md`, then
   [test-driven-implementation](../test-driven-implementation/SKILL.md).
5. Update task status and `JOURNAL.md` as work proceeds. Ask the Solution
   Architect to classify discovered improvements as in-scope or a follow-up.
6. Present code and validation for user review. After acceptance, invoke
   consolidation, user-doc, contributor-doc, or image-version skills only when
   requested or included in the approved plan.

For cross-repository requests, also use
[multi-repo-coordination](../multi-repo-coordination/SKILL.md). Keep separate
branches and Git histories with one request record in the primary repository.

The SPEC and PLAN are explicit approval gates. TASKS do not add a third gate.
Never merge or publish a release implicitly. Creating or pushing a `v*` tag
requires explicit authorization because it triggers image publication here.
