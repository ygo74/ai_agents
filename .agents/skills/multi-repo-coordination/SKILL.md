---
name: multi-repo-coordination
description: Coordinate changes across ai_agents and related Git repositories while preserving separate histories and one canonical request record.
---

# Multi-repository coordination

Identify the primary repository from the request's main outcome. Name each
repository's role and cross-repository contracts in SPEC. An Issue is optional.
Read every affected repository's local instructions and current consolidated
specification before planning.

Assign changes, task IDs, branches, prerequisites, validations, and pull
requests to the owning repository. Keep branches and Git histories separate;
keep one canonical request record in the primary repository and record
secondary status in its journal. Do not duplicate request histories or broaden
scope based on a related repository.

If another repository materially changes approved scope, update SPEC and PLAN
and obtain approval before implementation. Link related pull requests when
prepared; do not merge them.
