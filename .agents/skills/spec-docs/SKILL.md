---
name: spec-docs
description: Create or update simple-English Markdown feature specifications under spec/, explaining why a feature exists, its role, and its expected behavior. Use for design rationale, scope, contracts, and behavior; implementation guides and user instructions belong to the documentation skills.
---

# Feature Specifications

Write specifications that help readers understand why a capability exists,
what role it serves, and how it behaves. Use simple English for a team working
in a French-speaking environment. Keep exact domain and API terms where needed,
and explain them in plain language.

## Where to write

- Put specifications under `spec/`, grouped by domain or capability when that
  matches the repository structure.
- Use one focused page per feature or related behavior. Update `spec/README.md`
  or the relevant index when adding a page.
- Keep implementation and contributor guidance in `doc/contributors/`, and
  operational instructions in `doc/users/`. Link between these pages rather
  than copying large sections.

## What each specification explains

For the feature in scope, describe:

- **Why it exists:** the user or system problem, the need, and the reason for
  the chosen capability.
- **Role:** the responsibility it owns and the responsibilities it leaves to
  neighboring components.
- **Scope:** goals, non-goals, actors, and important terms.
- **Behavior:** inputs, outputs, state changes, ordering, defaults, and visible
  results for normal and failure cases.
- **Contracts and constraints:** interfaces, compatibility, security,
  lifecycle, performance, and operational requirements that affect the design.
- **Acceptance:** observable conditions that show the behavior is complete.

Use only sections that help explain the feature; do not fill a template with
empty headings.

## Evidence and clarity

1. Read the relevant existing specifications, repository instructions, and
   issue or design request.
2. Inspect the implementation, public interfaces, tests, and user documentation
   to distinguish current behavior from planned behavior.
3. Mark proposed, implemented, and unresolved behavior clearly. Do not present
   assumptions or future work as existing guarantees.
4. Explain important decisions and trade-offs in plain language. Avoid
   duplicating implementation details that change frequently unless they are
   part of a required contract.
5. Link to relevant domain pages, APIs, examples, and tests with
   repository-relative paths.

Write Markdown with descriptive headings, short paragraphs, and concrete
scenarios. Check terminology, links, and consistency with the source. Do not run
tests solely to write a specification unless the user asks for them.
