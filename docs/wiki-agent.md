# The Wiki Agent

An agent for online project documentation. It finds pages, reads them,
summarises them, answers questions **from them**, reports which documentation has
gone stale, and — on an explicit request, after an explicit confirmation — drafts
and publishes pages and comments.

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

| Capability | Reasons? | Changes the wiki? | What it does |
|---|---|---|---|
| `answer_from_wiki` | yes | no | searches, reads, answers with citations, flags ungrounded |
| `summarise_page` | yes | no | one page, with its comments, or with its children |
| `search_wiki` | no | no | structured query, returns references never bodies |
| `get_page` | no | no | one complete page |
| `get_page_children` | no | no | one level of the tree |
| `list_spaces` | no | no | the spaces this person may read |
| `get_comments` | no | no | the discussion of a page |
| `get_page_history` | no | no | who changed a page, when, and their note |
| `assess_page_freshness` | **no** | no | fresh / ageing / stale, arithmetically |
| `draft_page_content` | yes | **no** | composes a page body and stores it, publishing nothing |
| `create_page` | no | yes | publishes a draft as a new page |
| `update_page` | no | yes | replaces the body of a page with a draft |
| `add_comment` | no | yes | posts a comment on a page |
| `delete_page` | no | yes | removes a page |

`assess_page_freshness` drives no model on purpose. Whether a page has been
untouched for two hundred days is a subtraction of two dates: one right answer,
the same every run, at no cost. Asking a model would buy a plausible answer with
a chance of being wrong.

## Writing to the wiki

### Composing and publishing are two capabilities

`draft_page_content` composes a body and **writes nothing**. It stores the result
and hands the model an opaque reference. `create_page` and `update_page` take
that reference and nothing else.

The split is not ceremony. It is what makes the confirmation mean something: the
user approves a body resolved from the store, and the same body is what reaches
the wiki. A model cannot rewrite the content between the moment it is shown and
the moment it is written, because it never holds the content — only a reference
to it.

The same reasoning is why the LangGraph `edit` decision is refused. Letting a
human change the arguments *after* the approval was granted would run arguments
nobody confirmed, which is a confirmation bypass wearing the costume of a
feature. `ALLOWED_DECISIONS` is `("approve", "reject")`, and a security test pins
it.

Drafting is classified `READ`, and genuinely is one. Requiring the authoring
permission to *propose* text would gate an operation with no effect, and would
stop somebody who may read the wiki from preparing a page for a colleague to
publish.

### Four writes, deliberately not equal

| Capability | Risk | Permission | Floored in code? |
|---|---|---|---|
| `add_comment` | low | `wiki:comment` | no — a deployment may ungate it |
| `create_page` | medium | `wiki:author` | no |
| `update_page` | **high** | `wiki:author` | **yes** |
| `delete_page` | **high** | `wiki:manage` | **yes** |

`WikiSecurityFloor` pins `update_page` and `delete_page` at high risk with
confirmation always required, and a delivered skill package that tried to lower
either is refused when the manifest loads. Creating and commenting are not
floored: they add without removing, and a deployment that wants an agent to draft
pages unattended should be allowed to decide that. The floor holds the line at
operations that damage what already exists.

Note that `wiki:author` does not carry `wiki:manage`. Being able to write pages
is not being able to delete them.

### Two independent guards

The LangGraph human-in-the-loop middleware suspends a gated call before the tool
function runs, using an interrupt table built from the deterministic
`ConfirmationPolicy` — never from anything the model said. Separately,
`GatedWikiOperationRunner` re-checks the same policy inside the skill, so
invoking a skill directly, from a script or another framework, cannot bypass what
the framework enforces.

Both read the posture from `DeliveredWikiOperations`, the *same* source. Two
sources would allow a capability that is never asked about and always refused —
impossible to perform, and reported to the user as the wiki having refused.

### How an approval travels

The framework collects the answer; the domain enforces it. The
`WikiConfirmationPresenter` turns the raw arguments of a suspended call into the
request the user reads — resolving the draft so they see the actual body — and
the console resolver records that request and the answer in the confirmation
ledger. When the capability runs, `ConfirmationBroker` finds it there.

The join between the two halves is `ConfirmationKey`: the tool name and the
target. The presenter and the capability must produce the same one, or the
approval would not be found and a write the user authorised would fail as though
nobody had. That equality is asserted through the ledger in
`tests/unit/wiki/test_wiki_write_capabilities.py`, because a ledger lookup is
what actually happens at runtime.

An entry is consumed once, so one approval can never authorise two executions,
and a turn abandoned mid-approval discards the ledger: an answer given under one
premise must not authorise an operation in a later, unrelated turn.

### Losing a colleague's edit is a failure mode, not an edge case

A draft composed against a page carries the version it was composed against, and
`update_page` passes it on. If somebody edited the page in between, the write is
refused with `WikiConcurrentEditError` rather than silently discarding their
work — and the person who lost it would have had no way of knowing an agent did
it.

### What the audit trail holds

Every attempt that reaches the domain leaves a record: executed, blocked,
declined or failed, with the tool, the risk, the target page and the
confirmation request identifier. It never holds a page title or body, because a
trail is read by people who are not necessarily entitled to the content of the
page it names.

One honest caveat, shared with the Mail Agent: when the user declines at the
framework prompt, the tool function never runs, so **nothing is written to the
trail for that call**. The trail records what happened to the wiki, and nothing
happened. The `DECLINED` outcome is what the runner writes when a skill is
invoked directly with a refusal in hand.

### Enabling writes against a real Confluence

`WIKI_MCP_READ_ONLY` is the one switch, and it governs both halves at once. Its
value is handed to the server process — which exposes **no write tool** when it
is true, nine tools instead of nineteen — and it is read back through
`read_only_variable` in the binding, so the agent withdraws the four write
capabilities rather than advertising them.

Tying the two together is not decoration. Setting only one used to be possible,
and it produced the worst available outcome: the agent composed a revision, asked
the user to approve publishing it, and discovered `confluence_update_page` did
not exist only after the approval had been given. The binding and the server can
no longer disagree.

It ships `true`. Set it to `false` when writing is what the deployment is for;
the delivered `WIKI_MCP_TOOLSETS` already carries the page and comment tools the
four capabilities need. An unset or misspelled value reads as read-only, so a
typo costs a refusal rather than an unintended edit.

## A capability a server cannot serve is never offered

Bindings declare what a server really does. `sooperset/mcp-atlassian` exposes no
tool enumerating the revisions of a page, so `get_page_history` is absent from
its binding and the model never sees it. A tool the model can select but no
server can honour turns into a refusal mid-conversation, after the person has
already been told the agent could do it.

The rule extends to analysis capabilities: `summarise_page` needs `get_page`, and
`answer_from_wiki` needs `search_wiki` too. A server offering neither withdraws
both.

It matters most for the writes. A binding that declares no `update_page` is
usually a deployment running the server read-only, and offering the tool anyway
would have the agent promise an edit the server is configured to refuse.
`draft_page_content` needs `get_page`, because revising a page means reading it
first.

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
