# Contributor documentation

This guide explains how the agent repository is organized and where to change
each domain. It complements the [system specification](../../spec/README.md),
which records current responsibilities and behavior. Setup and operator
workflows remain in [`docs/`](../../docs/).

## Domains

- [Architecture and distributions](architecture.md)
- [Framework adapters](framework-adapters.md)
- [Shared core services and model providers](core-services.md)
- [Mail agent](mail-agent.md)
- [Wiki agent](wiki-agent.md)
- [Conversations and approvals](conversations-approvals.md)
- [MCP clients and dialects](mcp-clients.md)
- [MCP server distributions](mcp-servers.md)
- [Delivered configuration](configuration.md)
- [Tests and scenarios](testing.md)

## Before changing code

1. Read the relevant page here and its linked system specification.
2. Trace the current implementation and tests before changing an interface.
3. Keep framework code in its framework distribution and domain behavior in
   the Mail or Wiki application.
4. Update delivered manifests, bindings, prompts, tests, and user docs when the
   change affects them.

This repository has no root `AGENTS.md`. The root `README.md` describes local
setup, environments, and quality commands. The runtime repository has its own
contributor rules; consult them when changing a shared runtime API.
