---
name: spec-consolidation
description: Update the consolidated ai_agents specification to describe validated current behavior in spec/.
---

# Consolidate the system specification

For a request limited to consolidating current repository behavior, use this
skill directly after the repository branch is selected by
[development-workflow](../development-workflow/SKILL.md). Do not create or
update a development request SPEC or PLAN for consolidation-only work. If
consolidation is part of an implementation request, update the consolidated
specification after behavior is validated without amending the request SPEC or
PLAN solely for that documentation phase.

Use when requested or included in the approved plan. Start at `spec/README.md`
and inspect only the relevant architecture, agent behavior, or integration
page.
Use current implementation and tests as evidence; an approved design does not
prove that behavior was delivered.

Update the smallest fitting page, add a focused page only for durable system
behavior, and keep request history in `spec/implementation/`. Update the spec
index and related user/contributor guides or links when necessary. Preserve the
distinction between Mail/MAF and Wiki/LangGraph, and check security and
authorization claims against current code and tests.
