# AI Agent Lab

An enterprise AI agent laboratory.

Its purpose is to evaluate agentic AI frameworks and to establish the technical
foundations of a future enterprise agent platform.

Frameworks under evaluation:

- Microsoft Agent Framework
- LangChain
- CrewAI

Agents planned: Mail, Memory, Jira, Confluence, On-Prem RAG, Internet Research,
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
| Mail Agent | Microsoft Agent Framework 1.17 | Working. See [docs/mail-agent.md](./docs/mail-agent.md). |
| Mail MCP | our server, on the Gmail REST API | Working against a real mailbox, full coverage. |
| Mail MCP | our server, on a dataset | Working over stdio, validated by the conformance suite. |
| Mail MCP | official Google Gmail server | Bound and capability-checked; blocked by Workspace Developer Preview enrolment. |
| Mail Agent | LangChain, CrewAI | Not started. The skills are ready to be reused. |

## Layout

```text
src/ai_agent_lab/
  domain/          typed models, manifests, security primitives, reasoning ports
  mcp/             MCP tool contracts, catalogues and security floors
  skills/          reusable domain capabilities
  agents/          skill registry and capability bindings
  frameworks/      framework adapters (the only place importing a framework)
  infrastructure/  MCP clients, configuration loaders, in-memory doubles
  application/     composition root, CLI
config/            delivered configuration: agent, skill packages, MCP bindings
tests/             unit, contract, integration, agent, security, architecture
data/mail/         deterministic mailbox datasets
scenarios/mail/    reproducible agent scenarios
docs/              architecture and design documents
```

Layer boundaries are enforced by `tests/architecture/test_layer_boundaries.py`.

Instructions, tool descriptions, prompts, approval defaults and MCP tool names
live in `config/`, so they ship independently of the code. See
[docs/configuration.md](./docs/configuration.md).

## Getting started

Python 3.12 or later. One virtual environment per agent and per framework, so
framework dependencies never leak into a comparison.

```powershell
py -3.12 -m venv .venvs\mail-agent-maf
.\.venvs\mail-agent-maf\Scripts\python.exe -m pip install -e ".[maf,dev]"
Copy-Item .env.example .env
```

The core distribution is framework free; framework dependencies come from
extras (`.[maf]`). Add `.[azure]` for Entra ID authentication against Azure
OpenAI.

Pick the model provider in `.env`. `AGENT_CHAT_PROVIDER=openai` or
`AGENT_CHAT_PROVIDER=azure_openai`; see
[docs/mail-agent.md](./docs/mail-agent.md) for the Azure variables.

Run the Mail Agent against the local dataset - no Gmail, no mail credentials:

```powershell
$env:MAIL_AGENT_MODE = "mock"
$env:OPENAI_API_KEY  = "<your key>"
$env:OPENAI_CHAT_MODEL = "gpt-4o-mini"
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.application.mail
```

Run the checks:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m pytest tests -q
.\.venvs\mail-agent-maf\Scripts\python.exe -m ruff check src tests
.\.venvs\mail-agent-maf\Scripts\python.exe -m mypy
```

No test needs a network, an API key or a mailbox.

## Documentation

| Document | Content |
|---|---|
| [docs/architecture.md](./docs/architecture.md) | Layers, dependency rule, runtime modes. |
| [docs/agent-design.md](./docs/agent-design.md) | What an agent is, framework adapters, confirmation model. |
| [docs/mcp-design.md](./docs/mcp-design.md) | Tool contracts, tool surface, error translation. |
| [docs/mail-mcp-servers.md](./docs/mail-mcp-servers.md) | Which mail MCP servers are supported, and how to plug in another. |
| [docs/configuration.md](./docs/configuration.md) | What is delivered as configuration, and what stays in code. |
| [docs/mail-agent.md](./docs/mail-agent.md) | The Mail Agent: capabilities, skills, security, how to run it. |

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
