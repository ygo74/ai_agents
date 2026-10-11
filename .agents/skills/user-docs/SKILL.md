---
name: user-docs
description: Create or update simple-English Markdown documentation for users and operators, with domain pages, practical examples, and a complete end-to-end complex-agent example. Use for installation, configuration, operation, and user workflows; contributor architecture and feature specifications belong to the other documentation skills.
---

# User Documentation

Write documentation for people who install, configure, or use the repository's
runtime and agents. Use simple English for readers working in a French-speaking
environment. Explain product terms before using them and preserve exact command,
configuration, and API names.

## Where to write

- Put user and operator documentation under `doc/users/`.
- Create a focused page for each user-facing repository domain or capability.
- Maintain `doc/users/README.md` as the index when adding pages.
- Keep contributor architecture in `doc/contributors/` and feature rationale
  in `spec/`; link to those pages instead of mixing audiences.
- Keep runnable examples under `doc/examples/` when the repository has no more
  specific example convention. Link each example from its domain page.

## Domain pages and examples

Every domain page must include at least one practical example. Choose examples
that answer a real user task and show the required setup, input, command or API
call, and expected result. Verify names and behavior against the source,
configuration, existing examples, and tests. Do not invent options or promise
behavior that has not been confirmed.

For code examples:

- Include enough surrounding code to make the snippet understandable.
- Mark values that operators must supply, and never include real secrets.
- State prerequisites and where the command should be run.
- Explain expected output and what to do when the operation fails.
- Prefer complete, internally consistent examples over disconnected fragments.

## Complete complex-agent example

Maintain a dedicated worked guide at `doc/users/complete-agent.md`. It must
show how to build, configure, run, and call one complex agent using the runtime
features that this repository actually supports. Start by inventorying those
features from the code and public documentation. Cover their interaction in one
coherent example, including applicable areas such as agent construction,
managed hosting, authentication, discovery, conversations, streaming,
approvals, MCP tools, typed outputs, resource cleanup, and safe configuration.

For each feature, show where it enters the example and what the user observes.
If a feature is not supported, cannot be combined with the chosen design, or
needs an external service, say so plainly and do not simulate it as if it were
real. Keep secrets as environment-variable placeholders. Include prerequisites,
installation, configuration, launch, sample requests, expected responses, and
cleanup so a reader can follow the whole path.

## Writing and review

- Use direct, friendly language, short paragraphs, and numbered steps for
  procedures.
- Explain defaults, limits, permissions, errors, and operational effects where
  they matter to a user's decision.
- Use Markdown headings and fenced code blocks with language labels.
- Link to the relevant domain page, complete example, API contract, or support
  notes using repository-relative paths.
- Check links, commands, configuration names, and code examples. Do not run
  tests solely to write documentation unless the user asks for them.
