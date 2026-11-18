---
name: feature-specification
description: Turn a request about any agent capability or agent architecture into a reviewable SPEC using the relevant business or technical role.
---

# Feature specification

Start from the current system specification and read only the relevant agent,
integration, and user-guide pages. Inspect affected code, manifests,
permissions, tests, and docs enough to distinguish current behavior from the
request. Do not invent requirements and do not create an Issue.

Select one primary role based on the request outcome:

- For a primarily functional capability, read the
  [Business Analyst reference](references/business-analyst.md). This applies
  to Mail, Wiki, Jira/ticket management, user memory, orchestration, and future
  agents. Focus on user goals, workflows, outcomes, acceptance criteria, and
  safety expectations; then load only the behavior reference for the agents
  and capabilities in scope.
- For a primarily technical request (shared library use, framework integration,
  runtime hosting, architecture, or implementation details), read the Python
  Solution Architect reference in
  [implementation-plan/references](../implementation-plan/references/).
- For mixed requests, choose the role that matches the main outcome and record
  secondary concerns. Ask only if the main outcome cannot be inferred.

Use the [tracking artifact templates](../development-workflow/references/artifact-templates.md)
when useful. Follow the branch and tracking decision in
[development-workflow](../development-workflow/SKILL.md): create a new
`SPEC.md` only for a new request branch, or amend the SPEC already associated
with the continuing remote branch. Preserve its prior scope and record the new
request as a clearly marked amendment with acceptance criteria; do not create
a second folder for that branch. If the existing record cannot be identified
uniquely, stop and ask.

Store the canonical SPEC under
`spec/implementation/<issue-N-or-adhoc-slug>/` in the primary repository.
Record request source, repository scope, goal, current context, expected
behavior, acceptance criteria, out-of-scope items, constraints, risks, and open
decisions for the new request or amendment. Note security, permissions,
untrusted content, MCP, compatibility, docs, and deployment impacts when
relevant.

Present the complete new or amended SPEC, its path, summary, key decisions, and
open questions. Wait for explicit user approval before preparing or amending
the plan.
