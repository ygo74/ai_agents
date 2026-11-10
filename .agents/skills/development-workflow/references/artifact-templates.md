# Request tracking templates

Use these templates when the repository has no more specific format. Omit
irrelevant sections and add what makes an important decision reviewable.

## `SPEC.md`

```markdown
# Specification

## Request source and repositories
## Objective and current context
## Scope and exclusions
## Expected user behavior
## Architecture, permissions, and data
## Constraints and decisions
## Acceptance criteria
## Validation impact
## Risks and open questions
```

An Issue is optional. For cross-repository work, name primary and secondary
repositories and explain their roles.

## `PLAN.md`

```markdown
# Implementation Plan

## Approved SPEC
## Existing architecture and reuse analysis
## Repository and component scope
## Ordered steps and dependencies
## Test-first validation
## Security and deployment impact
## Documentation and examples
## Risks and completion criteria
```

Load the Business Analyst reference for a functional SPEC or the Python
Solution Architect reference for a technical SPEC and every implementation
PLAN.

## `TASKS.md`

```markdown
# Implementation Tasks

- [ ] AGENTS-001 Add a failing contract test; completion: ...; depends on: ...
- [ ] AGENTS-002 Implement the smallest behavior change; completion: ...; depends on: AGENTS-001
```

Order repository-scoped tasks, state observable completion criteria, and place
regression tests before the changes they protect.

## `JOURNAL.md`

Record approved scope, repositories and branches, progress, decisions, actual
validation commands/results, deviations, and architect-reviewed follow-up
proposals. Never mark a check passed unless it was run and passed.
```
