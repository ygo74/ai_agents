# The Wiki Agent

An agent for online project documentation. It finds pages, reads them,
summarises them, answers questions **from them**, and reports which documentation
has gone stale.

It runs on **LangChain / LangGraph**. The Mail Agent runs on Microsoft Agent
Framework. That is not an accident of history: the two exist to be compared, over
the same core, the same skill registry and the same security model.

## What it is not

It is not a document agent. A *wiki* here means online, collaborative, versioned,
hierarchical pages — Confluence, Notion, XWiki. Files that are read, extracted
from and rewritten (PDF, DOCX) are a different domain and would be a different
agent. The boundary is deliberate, and it is why the package is `wiki` and not
`docs`.

It is also not a Confluence agent. Nothing above the MCP boundary has heard of
Confluence: the domain speaks of spaces, pages and comments.

## Running it

Full instructions, including how to configure the MCP server, are in
[wiki-agent-running.md](./wiki-agent-running.md). The short version:

```powershell
py -3.12 -m scripts.install --env wiki-agent --into .venvs\wiki-agent
Copy-Item .env.example .env      # then set OPENAI_API_KEY and OPENAI_CHAT_MODEL
.\.venvs\wiki-agent\Scripts\wiki-agent.exe
```

From VS Code, press **F5** and pick a configuration from `.vscode/launch.json`.

| Variable | What it selects |
|---|---|
| `WIKI_AGENT_MODE` | `mock` (the delivered dataset) or `mcp` |
| `WIKI_MCP_SERVER` | `wiki-local` or `mcp-atlassian` |
| `WIKI_AGENT_USER_ID` | who the agent acts for — `diana` or `alice` in the dataset |
| `WIKI_MCP_ACCOUNT_ID` | who a single-account server acts for — see below |
| `WIKI_FRESHNESS_AGEING_AFTER_DAYS` | default 90 |
| `WIKI_FRESHNESS_STALE_AFTER_DAYS` | default 180 |

The model settings — `AGENT_CHAT_PROVIDER`, `OPENAI_*`, `AZURE_OPENAI_*` — are
the same ones the Mail Agent reads. Both agents must run against the same model,
or a comparison between the two frameworks measures two deployments instead.

## The three things this agent is careful about

### 1. An answer must be grounded, or say that it is not

A language model asked about a project produces a fluent answer whether or not
the documentation contains one. The whole value of this agent is the difference
between *"the wiki says X"* and *"the wiki does not say"*.

Three mechanisms enforce it, none of which is asking the model nicely:

- every citation is resolved against the pages **actually retrieved**. A page
  identifier the model invented — or one a planted instruction told it to cite —
  raises `UngroundedWikiResultError` rather than reaching the user as a source;
- an answer citing nothing is reported as ungrounded **whatever the model said
  about itself**, and the renderer puts that warning *before* the text, because a
  notice after a confident paragraph is a notice nobody reads;
- retrieving nothing raises rather than reaching the model at all.

### 2. A refusal is not an absence

A wiki restricts pages and spaces per person. `wiki_not_found` and
`wiki_access_denied` are kept distinct all the way from the server to the
conversation, because collapsing them would have the agent telling people the
documentation does not exist when in fact they may not see it. `AGENT.md` says so
in as many words, and the in-memory wiki reproduces both restriction levels so
the tests mean something.

The consequence for deployment: **the MCP server must carry the identity of the
person asking, never a shared service account.** An agent running as a service
account would read pages the user cannot see and summarise them back in perfect
good faith.

`sooperset/mcp-atlassian` over stdio has one set of credentials and no
per-request identity, so it acts as exactly one person. Set
`WIKI_MCP_ACCOUNT_ID` to who that is, and the dialect refuses to serve anybody
else rather than returning that person's view under another name.

### 3. Page content is data

A page is durable, edited by many people, often reachable by externals, and a
payload planted in it is read by every future question that touches it. That is
worse than an email, which one person reads once.

Every string a server returns — body, title, excerpt, comment, label, space name,
version note — is wrapped as `UntrustedText` at the dialect boundary, and fenced
with a per-rendering nonce before it reaches a prompt or a tool result. Section
labels carry identifiers and dates only: a page title in a label would be an
injection vector of its own.

The delivered dataset carries a planted instruction on `apollo-onboarding`
precisely so this cannot quietly rot.

## Capabilities

| Capability | Reasons? | What it does |
|---|---|---|
| `answer_from_wiki` | yes | searches, reads, answers with citations, flags ungrounded |
| `summarise_page` | yes | one page, with its comments, or with its children |
| `search_wiki` | no | structured query, returns references never bodies |
| `get_page` | no | one complete page |
| `get_page_children` | no | one level of the tree |
| `list_spaces` | no | the spaces this person may read |
| `get_comments` | no | the discussion of a page |
| `get_page_history` | no | who changed a page, when, and their note |
| `assess_page_freshness` | **no** | fresh / ageing / stale, arithmetically |

`assess_page_freshness` drives no model on purpose. Whether a page has been
untouched for two hundred days is a subtraction of two dates: one right answer,
the same every run, at no cost. Asking a model would buy a plausible answer with
a chance of being wrong.

All read-only in this increment. The write capabilities (`create_page`,
`update_page`, `add_comment`, `delete_page`) exist in the domain, the catalogue,
the security floor and both dialects; they are simply not delivered in
`config/agents/wiki/agent.yaml` yet.

## A capability a server cannot serve is never offered

Bindings declare what a server really does. `sooperset/mcp-atlassian` exposes no
tool enumerating the revisions of a page, so `get_page_history` is absent from
its binding and the model never sees it. A tool the model can select but no
server can honour turns into a refusal mid-conversation, after the person has
already been told the agent could do it.

The rule extends to analysis capabilities: `summarise_page` needs `get_page`, and
`answer_from_wiki` needs `search_wiki` too. A server offering neither withdraws
both.

## Confirmation, on LangGraph

The Mail Agent and this one gate operations the same way and reach the framework
differently:

| | Microsoft Agent Framework | LangGraph |
|---|---|---|
| Declaring a gate | `approval_mode="always_require"` | `interrupt_on={...}` |
| Reading what is suspended | `AgentResponse.user_input_requests` | `GraphOutput.interrupts` |
| Answering | `to_function_approval_response()` | `Command(resume={"decisions": [...]})` |
| State between turns | a session object | a `thread_id` and a checkpointer |

Both suspend **before** the tool runs, and in both the decision comes from the
same deterministic `ConfirmationPolicy`. Two LangChain features are refused:

- **`edit`** lets a human change the arguments after approving. The ledger records
  the confirmation against the exact request the user saw, so an edit would run
  arguments nobody confirmed — a confirmation bypass wearing the costume of a
  feature.
- **`respond`** delivers its message as a *successful* tool result. On an
  operation with side effects, a refusal would be indistinguishable from the
  operation having happened.

`allowed_decisions` is therefore `["approve", "reject"]`, fixed in code.

### The thread identifier

LangGraph keys persisted state by `thread_id`, and a conversation identifier is
supplied by the caller. Using it directly would let somebody resume another
person's conversation by guessing a string.

The identifier is `sha256(len(subject):subject:conversation)`. Both halves are
hashed together, with the subject length prefixed, so a subject containing the
separator cannot be shaped to collide with another subject's conversation — the
classic ambiguity of a delimiter in a composite key.

## Servers

See [wiki-mcp-servers.md](./wiki-mcp-servers.md) for the research behind
`sooperset/mcp-atlassian`, the Cloud-to-Data-Center story, and the security
advisories that make the version pin non-negotiable.

Two things that server does *not* do, which the dialect compensates for honestly
rather than silently:

- **it requires a title on every update.** The current title is read first and
  resent, otherwise a body-only edit would blank the page heading;
- **it has no optimistic concurrency.** `expected_version` is compared against
  the page just read, which *narrows* the window in which a colleague's edit is
  lost without closing it. That is better than ignoring it — it catches the
  ordinary case, where the other edit happened hours ago — and it is not an
  atomic compare-and-set.

## Notes for the framework comparison

Recorded while building, for `framework-comparison.md`:

- **Conversation state.** MAF holds it in a session object; LangGraph addresses
  it by an explicit `thread_id` against a checkpointer. LangGraph's is more
  work to wire and much easier to reason about — and it is the piece that needed
  a security decision.
- **Structured output.** `with_structured_output` returns the parsed model or
  raises; MAF returns a response whose `value` parses lazily. Both were
  translated into the same two domain errors.
- **Azure routing.** LangChain has a separate `AzureChatOpenAI` class; MAF routes
  one client by argument. LangChain's removes a category of misconfiguration —
  there is no way to end up on the OpenAI path while Azure variables are set — at
  the cost of a second import.
- **Tool binding.** LangGraph binds tools to the model on every call, which a
  test double must implement. MAF's function-invocation layer is composed
  instead.
- **Dependency weight.** Installing LangChain into the shared development
  environment downgraded `websockets` 17.1 → 16.1.1, a dependency of the Mail
  Agent's HTTP surface. This is the observation that made per-agent virtual
  environments a requirement rather than a preference.
