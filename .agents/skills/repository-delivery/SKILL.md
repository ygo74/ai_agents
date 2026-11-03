---
name: repository-delivery
description: Review and prepare validated ai_agents changes for repository delivery without merging or publishing implicitly.
---

# Repository delivery

Follow the approved plan and existing repository conventions. Review status,
the complete diff, links, secrets, generated files, and `git diff --check`;
run planned validations and report only actual results. Keep commits and pull
requests focused.

Push only the approved work branch and prepare a pull request when requested or
included in the approved plan. Never merge. Creating or pushing a `v*` tag
triggers image builds and publication to GHCR; obtain explicit user
authorization immediately before creating or pushing such a tag.
