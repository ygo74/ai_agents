---
name: image-version-bump
description: Prepare an ai_agents container image release version from Git tags and explain the publication triggered by v-prefixed tags.
---

# Image version bump

This repository has no package-version manifest. Its container release version
comes from Git tags in the form `vMAJOR.MINOR.PATCH`. Inspect existing tags,
the last released tag, and the changes since that tag before recommending the
next semantic version. Use patch for compatible fixes, minor for compatible
features, and major for breaking user-facing or deployment contracts. Explain
the evidence and affected images.

Check that the worktree and branch are suitable for release and that required
quality checks have passed. The `images.yml` workflow runs for `v*` tags and
builds, scans, and publishes the Mail Agent, Wiki Agent, and Gmail MCP images
to GHCR after quality succeeds. A tag is therefore a publication action.

By default, report the recommended version and exact release steps without
creating or pushing a tag. Create a local or remote tag only after the user
explicitly authorizes that specific release action. Do not force-move an
existing tag; stop if the selected version already exists.
