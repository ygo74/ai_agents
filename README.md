# AI Agent Lab

An enterprise AI agent laboratory.

Its purpose is to evaluate agentic AI frameworks and to establish the technical
foundations of a future enterprise agent platform.

Frameworks under evaluation:

- Microsoft Agent Framework — the Mail Agent
- LangChain / LangGraph — the Wiki Agent
- CrewAI — not started

Agents planned: Mail, Wiki, Memory, Jira, On-Prem RAG, Internet Research,
IT Project.

## The rule that shapes everything

Agents never integrate with enterprise systems. Every interaction goes through
tools exposed by MCP servers:

```text
User -> Agent -> Skill -> MCP Tool -> MCP Server -> Enterprise system
```

Domain models, skills, MCP contracts, scenarios and security policies are shared
across frameworks. Only orchestration adapters differ. The point is to compare
frameworks, not to build the same business logic three times.

## Status

| Agent | Framework | State |
|---|---|---|
| Mail Agent | Microsoft Agent Framework | Working. See [docs/mail-agent.md](./docs/mail-agent.md). |
| Wiki Agent | LangChain / LangGraph | Working, read-only. See [docs/wiki-agent.md](./docs/wiki-agent.md). |
| Mail MCP | our server, on the Gmail REST API | Working against a real mailbox, full coverage. |
| Mail MCP | our server, on a dataset | Working over stdio, validated by the conformance suite. |
| Mail MCP | official Google Gmail server | Bound and capability-checked; blocked by Workspace Developer Preview enrolment. |
| Wiki MCP | our server, on a dataset | Working over stdio, restrictions reproduced. |
| Wiki MCP | `sooperset/mcp-atlassian` | Bound and capability-checked. Cloud and Data Center. See [docs/wiki-mcp-servers.md](./docs/wiki-mcp-servers.md). |
| Third agent | CrewAI | Not started. The core and the skill registry are ready to be reused. |

## Layout

The repository ships ten distributions, each buildable and deployable on its
own. See [docs/repository-structure.md](./docs/repository-structure.md).

```text
agents/                          the products
  core/       ai_agent_lab.core       security, reasoning ports, manifests, skill registry
  maf/        ai_agent_lab.maf        Microsoft Agent Framework adapter
  langgraph/  ai_agent_lab.langgraph  LangChain / LangGraph adapter
  mail/       ai_agent_lab.mail       mail domain, skills, capabilities, composition root
  wiki/       ai_agent_lab.wiki       wiki domain, skills, capabilities, composition root
mcp-servers/                     auxiliaries, shipped separately
  protocol/       mail_mcp.protocol   wire payloads, tool names, error codes
  gmail/          mail_mcp.gmail      mail MCP server on the Gmail REST API
  reference/      mail_mcp.reference  mail MCP server on a dataset
  wiki-protocol/  wiki_mcp.protocol   wire payloads, tool names, error codes
  wiki-reference/ wiki_mcp.reference  wiki MCP server on a dataset
config/            delivered configuration: agents, skill packages, MCP bindings
tests/             unit, contract, integration, agent, security, architecture
data/              deterministic datasets
scenarios/         reproducible agent scenarios
docs/              architecture and design documents
```

No `mail_mcp` or `wiki_mcp` package imports `ai_agent_lab`: a server we write and
a server somebody else wrote are reached the same way, through a dialect on the
agent side. **No agent depends on two framework adapters.** Distribution and
layer boundaries are enforced by
`tests/architecture/test_distribution_boundaries.py`.

Instructions, tool descriptions, prompts, approval defaults and MCP tool names
live in `config/`, so they ship independently of the code. See
[docs/configuration.md](./docs/configuration.md).

## Getting started

Python 3.12 or later. **One virtual environment per agent**, so framework
dependencies never leak into a comparison. That is not tidiness: installing
LangChain alongside Microsoft Agent Framework has been observed to move a shared
transitive dependency under the other's feet.

```powershell
py -3.12 -m scripts.install --list                                  # what is on offer
py -3.12 -m scripts.install --env wiki-agent --into .venvs\wiki-agent
py -3.12 -m scripts.install --env mail-agent --into .venvs\mail-agent
py -3.12 -m scripts.install --env dev        --into .venvs\dev       # everything, for the tests
Copy-Item .env.example .env
```

Pick the model provider in `.env`: `AGENT_CHAT_PROVIDER=openai` or
`azure_openai`. Both agents read the same model settings, on purpose — a
comparison between two frameworks is only meaningful when both run against the
same model.

Run an agent against its local dataset — no Gmail, no Confluence, no credentials
beyond the model key:

```powershell
$env:OPENAI_API_KEY = "<your key>"
$env:OPENAI_CHAT_MODEL = "gpt-4o-mini"

.\.venvs\wiki-agent\Scripts\wiki-agent.exe
.\.venvs\mail-agent\Scripts\python.exe -m ai_agent_lab.mail.application
```

From VS Code, press **F5** and pick a configuration from `.vscode/launch.json`.
Each one points at the right virtual environment.

Run the checks, in the development environment:

```powershell
.\.venvs\dev\Scripts\python.exe -m pytest
.\.venvs\dev\Scripts\python.exe -m ruff check .
.\.venvs\dev\Scripts\python.exe -m mypy
```

No test needs a network, an API key, a mailbox or a wiki.

## Documentation

| Document | Content |
|---|---|
| [docs/architecture.md](./docs/architecture.md) | Layers, dependency rule, runtime modes. |
| [docs/repository-structure.md](./docs/repository-structure.md) | The distributions, the per-agent environments, how to plug a server. |
| [docs/agent-design.md](./docs/agent-design.md) | What an agent is, framework adapters, confirmation model. |
| [docs/mcp-design.md](./docs/mcp-design.md) | Tool contracts, tool surface, error translation. |
| [docs/configuration.md](./docs/configuration.md) | What is delivered as configuration, and what stays in code. |
| [docs/mail-agent.md](./docs/mail-agent.md) | The Mail Agent: capabilities, skills, security, how to run it. |
| [docs/mail-mcp-servers.md](./docs/mail-mcp-servers.md) | Which mail MCP servers are supported, and how to plug in another. |
| [docs/wiki-agent.md](./docs/wiki-agent.md) | The Wiki Agent: capabilities, grounding, confirmation on LangGraph. |
| [docs/wiki-agent-running.md](./docs/wiki-agent-running.md) | **How to run it, and how to configure the MCP server.** |
| [docs/wiki-mcp-servers.md](./docs/wiki-mcp-servers.md) | Which wiki MCP servers are supported, Cloud versus Data Center. |
| [docs/runtime-extraction-candidates.md](./docs/runtime-extraction-candidates.md) | What could move to `ygo74-agent-runtime`, and what must stay here. |

## Security

Security is an architectural concern, not a prompt.

- Credentials never leave the infrastructure layer and never reach a prompt, a
  log or a `UserContext`.
- Everything retrieved from an MCP server is untrusted data and is fenced before
  a model sees it, in reasoning prompts and in tool results alike.
- Write operations pass a deterministic confirmation policy. A model can propose
  an action; it never authorises one.
- Every state-changing attempt is audited with identifiers only.

Never commit a `.env`, a token or a credentials file.
