---
name: contributor-docs
description: Create or update simple-English Markdown technical documentation for repository contributors, including domain pages and architecture diagrams. Use for contributor guides, code architecture, and runtime flow documentation; user guides and feature rationale belong to the other documentation skills.
---

# Contributor Documentation

Write technical documentation for people who modify or maintain this repository.
Keep the prose in simple English for a team that works in a French-speaking
environment. Keep source identifiers, API names, and code examples unchanged.

## Where to write

- Put contributor documentation under `doc/contributors/`.
- Keep one focused page for each repository domain, such as sessions, security,
  endpoints, discovery, approvals, or MCP. Use the domains that actually exist
  in this repository.
- Maintain `doc/contributors/README.md` as the index when adding domain pages.
- Keep feature specifications in `spec/`; link to them when useful instead of
  duplicating their rationale.

## Research and accuracy

1. Read the repository's `AGENTS.md`, top-level README, and existing relevant
   `doc/` and `spec/` pages.
2. Trace each documented flow through the implementation, public interfaces,
   configuration, and tests. Treat tests as evidence of behavior, not as a
   substitute for understanding the implementation.
3. Explain what each domain owns, its public contracts, important classes or
   modules, dependencies, lifecycle, error paths, and extension points.
4. Separate supported behavior from examples, assumptions, and future ideas.
   Do not claim a guarantee, dependency, or feature that the source does not
   support.

## Diagrams

Technical pages must include Mermaid diagrams when the domain has meaningful
class relationships or execution flow:

- Use `classDiagram` to show important classes or protocols and their
  dependency or implementation relationships.
- Use `sequenceDiagram` to show the order of calls for a representative flow,
  including relevant boundaries such as HTTP, runtime, framework, and domain.
- Label arrows with the actual responsibility or call. Keep diagrams focused
  on the page's domain and consistent with the code.

Do not draw a diagram just to restate a list. If a domain has no meaningful
class or call relationships, state why a diagram would not clarify it.

## Writing and review

- Use short headings, short sentences, active voice, and defined terms.
- Prefer a small Markdown table for a concise mapping; use lists for procedures.
- Link to source files, tests, neighboring domain pages, and specifications
  using repository-relative paths.
- Keep contributor guidance focused on design and maintenance. Put setup and
  end-user workflows in `doc/users/`.
- Check links, code names, and Mermaid syntax. Do not run tests solely to write
  documentation unless the user asks for them.
