---
name: implementation-tasks
description: Convert an approved Python architecture plan into ordered implementation tasks with observable test-first completion criteria.
---

# Implementation tasks

Use after PLAN approval. Read the [tracking artifact templates](../development-workflow/references/artifact-templates.md)
and Python Solution Architect reference, then convert the approved plan into
`TASKS.md` in the canonical tracking directory.

Order tasks by dependency. Name the repository and affected modules for each
task; state prerequisites, observable completion criteria, and validation.
Place a failing regression or contract test before the implementation task it
protects. Include configuration, docs, examples, security, architecture, and
deployment work only when required by the approved scope.

The task list is the implementation checklist; it does not need an additional
user approval.
