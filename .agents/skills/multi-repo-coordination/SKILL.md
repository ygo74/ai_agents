---
name: multi-repo-coordination
description: Coordinate changes across ai_agents and related Git repositories while preserving separate histories and one canonical request record.
---

# Multi-repository coordination

Identify the primary repository from the request's main outcome. Name each
repository's role and cross-repository contracts in SPEC. An Issue is optional.
For every affected repository independently, inspect the working tree and
current branch and successfully refresh `origin` (for example, with
`git fetch origin --prune`) before selecting a branch. Verify `origin/main`
before basing a branch on it.
Continue on a non-main branch that still exists on `origin`; from `main` or a
non-main branch no longer on `origin`, create a request branch from the latest
`origin/main`. Preserve uncommitted changes and old local branches; do not
switch with uncommitted work or use stale remote refs. If origin cannot be
refreshed, stop before deciding.

Keep one canonical SPEC/PLAN/TASKS/JOURNAL in the primary repository. If its
current non-main branch still exists on `origin`, update the uniquely matching
request record in place. Find it by Issue identifier, branch recorded in
`JOURNAL.md`, and request scope; prefer the matching record whose TASKS/JOURNAL
show related work is active. If the relevant record is ambiguous, ask the user;
do not create a competing folder. If the primary repository is on `main` or its
branch no longer exists on `origin`, create new canonical tracking on the new
request branch. Record secondary branch choices and validation in the primary
journal; do not duplicate request tracking in secondary repositories.

Read every affected repository's local instructions and current consolidated
specification before planning.

Assign changes, task IDs, branches, prerequisites, validations, and pull
requests to the owning repository. Keep branches and Git histories separate;
keep one canonical request record in the primary repository and record
secondary status in the canonical journal. Do not duplicate request histories
or broaden scope based on a related repository.

If another repository materially changes approved scope, update the existing
canonical SPEC and PLAN and obtain approval before implementation. Link related
pull requests when prepared; do not merge them.
