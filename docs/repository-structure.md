# Repository structure

The repository ships **six distributions** across **two namespaces**. Each is
buildable, installable and deployable on its own.

```text
agents/                     the product
  core/      ai-agent-lab-core         ai_agent_lab.core
  maf/       ai-agent-lab-maf          ai_agent_lab.maf
  mail/      ai-agent-lab-mail-agent   ai_agent_lab.mail
mcp-servers/                auxiliaries
  protocol/  mail-mcp-protocol         mail_mcp.protocol
  gmail/     mail-mcp-gmail            mail_mcp.gmail
  reference/ mail-mcp-reference        mail_mcp.reference
```

| Distribution | Depends on |
|---|---|
| `ai-agent-lab-core` | pydantic, pydantic-settings, pyyaml, python-dotenv |
| `ai-agent-lab-maf` | core, agent-framework; extra `azure` |
| `ai-agent-lab-mail-agent` | core, mcp; extras `maf`, `native` |
| `mail-mcp-protocol` | pydantic; extra `serving` adds mcp |
| `mail-mcp-gmail` | protocol[serving], mcp, httpx |
| `mail-mcp-reference` | protocol[serving], mcp |

## The rule that matters

**No `mail_mcp` package imports `ai_agent_lab`.**

A mail server does not know what an agent is, what a skill is, or what our
domain models look like. That is not politeness: it is what makes a server we
wrote and a server somebody else wrote interchangeable. The moment one of ours
depended on our domain, a third-party server would become a second-class
citizen, and the whole point of the boundary would be lost.

`tests/architecture/test_distribution_boundaries.py` enforces this, along with
the sub-layers of the mail agent and the absence of any `__init__.py` at a
namespace root.

## The protocol is a shortcut, not a condition

`mail_mcp.protocol` carries the ten tool names, the wire payloads and the error
codes. Nothing but `str`, `datetime`, `int` and `bool` — no domain model, no
security metadata, no untrusted-content wrapper.

A server that implements it needs no code on the agent side: `dialect: native`
in its binding, and it works. That is an offer to server authors, never a
requirement.

`mail_mcp.protocol.serving` goes further and hands a server the ready-made
FastMCP surface for the ten tools. Both of our servers use it, which is what
makes the reference server a meaningful conformance target: it and the Gmail
server cannot drift apart.

## Plugging a server that never heard of us

This is the normal case. The official Google server, a server for Yahoo, one for
Fastmail, the EWS server: none of them speaks our protocol. The translation
happens **on the agent side**, in a dialect.

Three steps, and none of them touch the domain, the skills or the agent:

1. Write a class implementing `MailTools` (`ai_agent_lab.mail.tools_port`),
   translating that server's shapes into mail domain models. Fence every piece
   of third-party free text as `UntrustedText`.
2. Register it in `ai_agent_lab.mail.mcp.dialects.MailDialectRegistry`.
3. Deliver `config/mcp/<server>.yaml` declaring the transport, `dialect:`, the
   capabilities the server really has, and the name it gives to each tool.

```yaml
server: bluebird
transport: stdio
command: python
args: [-m, bluebird.server]
dialect: bluebird
capabilities: [search_mail, get_mail, get_thread, list_labels, mark_read]
tools:
  search_mail: bluebird.findMail
  get_mail: bluebird.readMail
```

A capability the binding does not declare is never advertised to the model, so a
gap in a server is a configuration fact rather than a failure on the first call.

`tests/unit/test_mail_dialect_registry.py` makes this claim executable with a
fictional server.

| Server | Dialect | Knows our protocol |
|---|---|---|
| Reference, Gmail API (ours) | `native` | yes |
| Official Google | `gmail` | no |
| Yahoo, Fastmail, … | its own | no |
| EWS | either | your choice |

One reservation: a server returning **prose** rather than structured JSON is
still pluggable, but its dialect has to parse text. That is fragile and exposed
to injection through message content, as documented for the community Gmail
servers in [mail-mcp-servers.md](./mail-mcp-servers.md). Being able to plug such
a server is not a recommendation to do so.

## Installing

```powershell
py -3.12 -m venv .venvs\mail-agent-maf
.\.venvs\mail-agent-maf\Scripts\python.exe -m scripts.install
```

The script installs the six distributions in editable mode, in dependency order,
plus the development tools. Order matters: pip must resolve each local name
against the copy in this working tree rather than looking for it on an index.

To prove the Gmail server needs neither the agent nor a framework, give it an
environment of its own:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m scripts.install --gmail-venv .venvs\mail-mcp-gmail
```

That environment gets `mail-mcp-protocol` and `mail-mcp-gmail`, and nothing
else. The binding in `config/mcp/gmail-api.yaml` can then point its `command` at
that interpreter, and the two processes share nothing but stdio.

## Console commands

| Command | What it does |
|---|---|
| `mail-agent` | Runs the Mail Agent |
| `mail-mcp-reference` | Serves the dataset over MCP |
| `mail-mcp-gmail` | Serves a real mailbox over MCP |
| `mail-mcp-gmail-authorise` | One-off Google consent |

## Adding an agent

Create `agents/<name>/` with its own `pyproject.toml`, a `src/ai_agent_lab/<name>/`
tree, and no `__init__.py` at the `ai_agent_lab` level — that would turn the
namespace into a regular package and hide every sibling. Add it to
`DISTRIBUTIONS` in `scripts/install.py` and to the tables in the root
`pyproject.toml` and in the architecture test.

Reuse `ai_agent_lab.core` and, if it targets Microsoft Agent Framework,
`ai_agent_lab.maf`. A LangChain or CrewAI adapter is a sibling of `agents/maf/`,
not a change inside it.
