---
name: repository-delivery
description: Review and prepare validated ai_agents changes for repository delivery without merging or publishing implicitly.
---

# Repository delivery

Follow the approved plan and existing repository conventions. Review status,
the complete diff, links, secrets, generated files, and `git diff --check`;
run planned validations and report only actual results. Keep commits and pull
requests focused.

When a commit or push is requested, follow the
[origin-push skill](../origin-push/SKILL.md). It requires Ruff and pytest for
every change that includes Python files.

Push only the approved work branch and prepare a pull request when requested or
included in the approved plan. Never merge. Creating or pushing a `v*` tag
triggers image builds and publication to GHCR; obtain explicit user
authorization immediately before creating or pushing such a tag.
