# Architecture and distributions

## Dependency direction

The repository ships ten independently buildable Python distributions. Mail
uses Microsoft Agent Framework, Wiki uses LangChain/LangGraph, and the MCP
servers are separate processes. Agent distributions share core configuration
and the external `ai-enterprise-agent-runtime`; they do not import each other's
framework adapter.

```mermaid
flowchart TD
    Runtime[ai-enterprise-agent-runtime]
    Core[ai-agent-lab-core]
    MAF[ai-agent-lab-maf]
    LG[ai-agent-lab-langgraph]
    Mail[ai-agent-lab-mail-agent]
    Wiki[ai-agent-lab-wiki-agent]
    MailProtocol[mail-mcp-protocol]
    WikiProtocol[wiki-mcp-protocol]
    MailServer[Mail MCP servers]
    WikiServer[Wiki MCP servers]
    Runtime --> Core
    Core --> MAF
    Core --> LG
    MAF --> Mail
    LG --> Wiki
    Runtime --> Mail
    Runtime --> Wiki
    MailProtocol --> MailServer
    WikiProtocol --> WikiServer
    Mail --> MailProtocol
    Wiki --> WikiProtocol
```

The graph is a responsibility map; consult each `pyproject.toml` for exact
extras and version constraints. `scripts/install.py` encodes environment
membership and dependency install order. Keep framework packages out of the
shared core and use one virtual environment per agent deployment.

## Layer rule

Within an agent, the composition root constructs concrete dependencies. Skills
depend on domain ports and runtime contracts. MCP dialects implement the
domain ports. MCP server packages depend on wire protocol packages and never
import `ai_agent_lab`.

```mermaid
classDiagram
    class MailAgentCompositionRoot
    class WikiAgentCompositionRoot
    class MailSkillsFactory
    class WikiSkillsFactory
    class MailTools
    class WikiTools
    class MailToolsProvider
    class WikiToolsProvider
    MailAgentCompositionRoot --> MailSkillsFactory : wires
    WikiAgentCompositionRoot --> WikiSkillsFactory : wires
    MailSkillsFactory --> MailTools : consumes port
    WikiSkillsFactory --> WikiTools : consumes port
    MailAgentCompositionRoot --> MailToolsProvider : selects backend
    WikiAgentCompositionRoot --> WikiToolsProvider : selects backend
```

`tests/architecture/test_distribution_boundaries.py` enforces package and
layer constraints. The [repository structure specification](../../spec/architecture/repository-structure.md)
lists each distribution and its role.

Useful source: [`agents/`](../../agents/), [`mcp-servers/`](../../mcp-servers/),
and [`scripts/install.py`](../../scripts/install.py).
