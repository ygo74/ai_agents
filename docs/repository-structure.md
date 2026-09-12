# Repository structure

The repository ships **ten distributions** across **three namespaces**. Each is
buildable, installable and deployable on its own.

```text
agents/                     the products
  core/       ai-agent-lab-core          ai_agent_lab.core
  maf/        ai-agent-lab-maf           ai_agent_lab.maf
  langgraph/  ai-agent-lab-langgraph     ai_agent_lab.langgraph
  mail/       ai-agent-lab-mail-agent    ai_agent_lab.mail
  wiki/       ai-agent-lab-wiki-agent    ai_agent_lab.wiki
mcp-servers/                auxiliaries
  protocol/       mail-mcp-protocol      mail_mcp.protocol
  gmail/          mail-mcp-gmail         mail_mcp.gmail
  reference/      mail-mcp-reference     mail_mcp.reference
  wiki-protocol/  wiki-mcp-protocol      wiki_mcp.protocol
  wiki-reference/ wiki-mcp-reference     wiki_mcp.reference
```

| Distribution | Depends on |
|---|---|
| `ai-agent-lab-core` | pydantic, pydantic-settings, pyyaml, python-dotenv, ygo74-agent-runtime |
| `ai-agent-lab-maf` | core, agent-framework; extra `azure` |
| `ai-agent-lab-langgraph` | core, langchain, langgraph, langchain-openai; extra `azure` |
| `ai-agent-lab-mail-agent` | core, mcp; extras `maf`, `native`, `http` |
| `ai-agent-lab-wiki-agent` | core, mcp; extras `langgraph`, `native`, `http` |
| `mail-mcp-protocol` | pydantic; extra `serving` adds mcp |
| `mail-mcp-gmail` | protocol[serving], mcp, httpx |
| `mail-mcp-reference` | protocol[serving], mcp |
| `wiki-mcp-protocol` | pydantic; extra `serving` adds mcp |
| `wiki-mcp-reference` | wiki-protocol[serving], mcp |

`ygo74-agent-runtime` is the odd one out: it is not developed here. It owns the
security model, the authenticated caller, the conversation port and the capability
contracts that `ai-agent-lab-core` used to carry, so it is a foundation dependency
rather than a serving extra. Because it is developed alongside this repository,
link a working copy instead of resolving the published wheel:

```powershell
python -m scripts.install --environment dev --runtime-source <path-to-checkout>
```

## The two agents

They exist to be compared. Same core, same registry, same security model,
different agentic framework:

| | Mail Agent | Wiki Agent |
|---|---|---|
| Domain | a mailbox | online project documentation |
| Framework | Microsoft Agent Framework | LangChain / LangGraph |
| Adapter | `ai_agent_lab.maf` | `ai_agent_lab.langgraph` |
| Confirmation | `approval_mode="always_require"` | `HumanInTheLoopMiddleware` |
| Third-party server | the official Google server | `sooperset/mcp-atlassian` |

`tests/architecture/test_distribution_boundaries.py` asserts that **no agent
depends on two framework adapters**. Measuring two frameworks in one process
measures neither.

## The rule that matters

**No `mail_mcp` or `wiki_mcp` package imports `ai_agent_lab`.**

A server does not know what an agent is, what a skill is, or what our domain
models look like. That is not politeness: it is what makes a server we wrote and
a server somebody else wrote interchangeable. The moment one of ours depended on
our domain, a third-party server would become a second-class citizen, and the
whole point of the boundary would be lost.

`tests/architecture/test_distribution_boundaries.py` enforces this, along with
the sub-layers of each agent and the absence of any `__init__.py` at a namespace
root.

## The protocol is a shortcut, not a condition

`mail_mcp.protocol` carries twelve tool names and `wiki_mcp.protocol` ten, plus
the wire payloads and the error codes. Nothing but `str`, `datetime`, `int` and
`bool` — no domain model, no security metadata, no untrusted-content wrapper.

A server that implements one needs no code on the agent side: `dialect: native`
in its binding, and it works. That is an offer to server authors, never a
requirement.

`<namespace>.protocol.serving` goes further and hands a server the ready-made
FastMCP surface. Our servers use it, which is what makes each reference server a
meaningful conformance target.

## Plugging a server that never heard of us

This is the normal case. The official Google server, `sooperset/mcp-atlassian`, a
server for Yahoo, the EWS server: none of them speaks our protocol. The
translation happens **on the agent side**, in a dialect.

Three steps, and none of them touch the domain, the skills or the agent:

1. Write a class implementing the tool port (`MailTools`, `WikiTools`),
   translating that server's shapes into domain models. Fence every piece of
   third-party free text as `UntrustedText`.
2. Register it in the agent's dialect registry.
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

| Server | Dialect | Knows our protocol |
|---|---|---|
| Reference, Gmail API (ours) | `native` | yes |
| Official Google | `gmail` | no |
| `sooperset/mcp-atlassian` | `atlassian` | no |
| Yahoo, Fastmail, … | its own | no |
| EWS | either | your choice |

One reservation: a server returning **prose** rather than structured JSON is
still pluggable, but its dialect has to parse text. That is fragile and exposed
to injection through the content itself, as documented for the community Gmail
servers in [mail-mcp-servers.md](./mail-mcp-servers.md). Being able to plug such
a server is not a recommendation to do so.

## Installing

An **environment** is a deployment unit: the set of distributions one thing needs
and nothing more.

```powershell
py -3.12 -m scripts.install --list
py -3.12 -m scripts.install --env wiki-agent --into .venvs\wiki-agent
```

| Environment | Holds |
|---|---|
| `dev` | everything, plus the development tools |
| `mail-agent` | the Mail Agent — **no LangChain package** |
| `wiki-agent` | the Wiki Agent — **no agent-framework package** |
| `mail-mcp-gmail` | the Gmail server, alone |
| `wiki-mcp-reference` | the reference wiki server, alone |

**Each agent gets its own environment**, and that is not tidiness for its own
sake. Installing both agents in one place has been observed to move a shared
transitive dependency under the other's feet, and a framework comparison run in a
contaminated environment measures the contamination.

`dev` is the exception, and a necessary one: the architecture tests scan every
distribution, so the environment the suite runs in has to hold all of them.

Order matters within an environment: pip must resolve each local name against the
copy in this working tree rather than looking for it on an index.

## Console commands

| Command | What it does |
|---|---|
| `mail-agent` | Runs the Mail Agent |
| `wiki-agent` | Runs the Wiki Agent |
| `mail-mcp-reference` | Serves the mail dataset over MCP |
| `wiki-mcp-reference` | Serves the wiki dataset over MCP |
| `mail-mcp-gmail` | Serves a real mailbox over MCP |
| `mail-mcp-gmail-authorise` | One-off Google consent |

## Adding an agent

Create `agents/<name>/` with its own `pyproject.toml`, a `src/ai_agent_lab/<name>/`
tree, and no `__init__.py` at the `ai_agent_lab` level — that would turn the
namespace into a regular package and hide every sibling. Add it to `ENVIRONMENTS`
in `scripts/install.py`, to the tables in the root `pyproject.toml` and to
`DISTRIBUTIONS` in the architecture test.

Reuse `ai_agent_lab.core` and one framework adapter. A CrewAI adapter is a
sibling of `agents/maf/` and `agents/langgraph/`, not a change inside either.

