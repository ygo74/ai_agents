---
name: development-workflow
description: Route ad hoc or Issue-linked changes through approved specifications, architecture plans, implementation tasks, and test-driven delivery.
---

# Development workflow

Start by classifying the request and checking repository state. An Issue may be
linked, but is optional and must never be created unless requested.

For a request limited to user documentation, contributor documentation, or
global specification consolidation, do not create or update a development
request SPEC/PLAN. Apply the branch selection rules below, then invoke the
corresponding skill directly. If the request also changes implementation
behavior, use the full development workflow.

For each affected repository, inspect its working tree and current branch, then
successfully refresh `origin` (for example, with `git fetch origin --prune`)
before choosing a branch. Do not use stale remote-tracking refs as evidence of
a live remote branch; verify `origin/main` before basing a new branch on it.

- If the current branch is `main`, fetch the latest `origin/main` and create a
  request branch from it. Create a new canonical SPEC and PLAN in the primary
  repository.
- If the current branch is not `main` and still exists on `origin`, continue on
  that branch. Update its existing canonical SPEC and PLAN in place; do not
  create another tracking folder.
- If the current branch is not `main` and no longer exists on `origin`, fetch
  the latest `origin/main` and create a new request branch from it. Preserve
  the old local branch and commits, and create a new canonical SPEC and PLAN
  in the primary repository.

Do not switch branches with uncommitted changes or discard them. If `origin`
cannot be refreshed, stop before making a branch decision. For an existing
remote branch, identify the relevant tracking folder by its Issue identifier,
branch in `JOURNAL.md`, and request scope. Prefer the single record whose
TASKS/JOURNAL show the related work is active. If the relevant record is still
ambiguous, ask which one to continue instead of creating a new one. In a
multi-repo request, make the branch decision independently in every repository
while keeping the sole canonical SPEC/PLAN/TASKS/JOURNAL in the primary
repository; record secondary branch state in the canonical journal.

1. Identify the primary and secondary repositories, apply branch selection,
   then read local `AGENTS.md`, `WORKFLOW.md`, and only relevant consolidated
   pages.
2. Use [feature-specification](../feature-specification/SKILL.md) to create a
   new canonical `SPEC.md` or amend the existing branch's SPEC. Present the
   complete current SPEC and wait for explicit approval.
3. After approval, use [implementation-plan](../implementation-plan/SKILL.md)
   to inspect the current architecture and create or amend `PLAN.md`. Present
   the complete current plan and wait for explicit approval.
4. After plan approval, use [implementation-tasks](../implementation-tasks/SKILL.md)
   to create or extend the ordered `TASKS.md`, then use
   [test-driven-implementation](../test-driven-implementation/SKILL.md).
5. Update task status and `JOURNAL.md` as work proceeds. Ask the Solution
   Architect to classify discovered improvements as in-scope or a follow-up.
6. Present code and validation for user review. After acceptance, invoke
   consolidation, user-doc, contributor-doc, or image-version skills when
   requested or included in the approved plan; those phases do not require
   amendments to SPEC/PLAN unless implementation scope also changes.

For cross-repository requests, also use
[multi-repo-coordination](../multi-repo-coordination/SKILL.md). Keep separate
branches and Git histories with one request record in the primary repository.

The SPEC and PLAN, including their amendments, are explicit approval gates.
TASKS do not add a third gate.
Never merge or publish a release implicitly. Creating or pushing a `v*` tag
requires explicit authorization because it triggers image publication here.
