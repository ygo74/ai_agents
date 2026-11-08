---
name: spec-consolidation
description: Update the consolidated ai_agents specification to describe validated current behavior in spec/.
---

# Consolidate the system specification

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
