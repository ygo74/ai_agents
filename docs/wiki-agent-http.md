# Serving the Wiki Agent over HTTP

The command line drives one person's view of the wiki. Serving the agent over
HTTP is what lets LibreChat talk to it, and later what lets an aggregator agent
call it.

It is the same surface as [the Mail Agent's](./mail-agent-http.md), built from
the same pieces, and that is the point: the two agents run on two different
agentic frameworks, so anything written twice would make a comparison between
them a comparison of two web layers instead.

Two things change from the console, and only two: the caller is established by
the transport instead of by `.env`, and a confirmation can no longer block a
turn.

## What runs the HTTP surface

Routes, OpenAI request shapes, JWT validation and discovery come from
[`ygo74-agent-runtime`](https://github.com/ygo74/ai-enterprise-agent-runtime). We
do not reimplement them.

| Owned by the runtime library | Owned here |
|---|---|
| `POST /v1/chat/completions`, `GET /v1/models` | Which caller a request is attributed to |
| OpenAI payload normalisation | Which conversation it continues |
| JWT / API-key authentication | What happens to a gated operation |
| Discovery and access policy | Isolation and eviction of conversation state |

What the repository owns is written once, in `ai_agent_lab.core.serving`, and
composed by both agents:

| Module | Responsibility |
|---|---|
| `serving/payloads.py` | Reads the loosely-typed request into a typed `ConversationTurn` |
| `serving/confirmations.py` | Runs the operation a claimed ticket describes |
| `serving/pending.py` | Renders what is waiting, so it can be answered by name |
| `serving/discovery.py` | Builds the descriptor from the delivered manifest |
| `serving/runtimes.py` | Keeps one runtime per caller and conversation, bounded and expiring |

What is specific to this agent is small, and deliberately so:
`application/entrypoints/` and `application/approval/tickets.py`.

## Running it

```powershell
$env:WIKI_AGENT_MODE = "mock"
$env:WIKI_AGENT_HTTP_API_KEY = "demo-key"
.\.venvs\wiki-agent\Scripts\python.exe -m uvicorn `
  "ai_agent_lab.wiki.application.entrypoints.service:build_app" --factory --port 8124
```

```powershell
curl -Method POST http://127.0.0.1:8124/v1/chat/completions `
  -Headers @{"x-api-key" = "demo-key"} `
  -Body '{"model":"wiki-agent","messages":[{"role":"user","content":"what is in scope for Apollo?"}]}'
```

VS Code has `Wiki Agent — HTTP (mock)` and `Wiki Agent — HTTP (mcp-atlassian
HTTP)` configurations that do the same on port 8124 with the debugger attached.
The Mail Agent uses 8123, so both can run at once.

### Settings

| Variable | Meaning |
|---|---|
| `WIKI_AGENT_HTTP_API_KEY` | One key, one caller. For demonstrations only. |
| `WIKI_AGENT_HTTP_OIDC_ISSUER` | Keycloak realm URL. Once set, the API key is ignored. |
| `WIKI_AGENT_HTTP_OIDC_AUDIENCE` | Audience the token must carry. Default `wiki-agent`. |
| `WIKI_AGENT_HTTP_ROLES_CLAIM_PATH` | Where roles live in the token. Default `realm_access.roles`. |
| `WIKI_AGENT_HTTP_MAX_CONVERSATIONS` | Ceiling on live conversations. Default 200. |
| `WIKI_AGENT_HTTP_IDLE_MINUTES` | How long an untouched conversation is kept. Default 30. |

**The service refuses to start with neither.** That is not pedantry on a wiki:
pages and spaces are restricted per person, so an anonymous caller would be
served *somebody's* view of the wiki without anyone having decided whose.
Starting and failing later would be worse - the misconfiguration would surface as
an odd answer rather than as a refusal to run.

Authentication is always required once it does start, whichever credential is
configured. The runtime's authenticator chain accepts the API key as well as a
bearer token, so this is not "tokens only": it is "something, always".

### A caller needs no e-mail address

The Mail Agent refuses a caller whose identity carries no address, because a
mailbox is addressed by one and defaulting it would pick a victim. A wiki account
is not an address: Confluence Cloud identifies a person by an account identifier
and Data Center by a username, and an identity provider may assert neither.

So this agent reads its principal with `require_email=False`. The subject stays
mandatory - it is what every ticket, ledger entry and audit record is partitioned
by - and an address is kept when the provider does assert one. Nothing is
invented, because an invented address would then appear in every audit record
this caller produces.

## Confirmations, without a side channel

At a console the agent asks and waits. An HTTP request must be answered, so a
gated operation ends its turn **unperformed** and comes back as a ticket:

```text
> add a comment to the architecture page saying the queue is live

I have asked for confirmation.

Awaiting your confirmation - nothing has been changed yet:

- **Post this comment?**
  - Page: apollo-architecture
  - Comment: the queue is live
  - Reply `CONFIRM cfm-1a2b3c4d5e6f` to approve, `CANCEL cfm-1a2b3c4d5e6f` to decline.

> CONFIRM cfm-1a2b3c4d5e6f

add_comment succeeded.
```

Why this is not a weakening of the console behaviour:

- the first turn declines every suspended call, so nothing runs while it is only
  described;
- the ticket stores the **exact arguments**, and confirming re-invokes the
  capability from them - the model plays no part in the second turn and cannot
  change what was described;
- `CONFIRM` is read by a literal parser *before* the model sees the message, so a
  model can never approve anything, and a sentence merely mentioning a ticket is
  an ordinary question;
- a ticket is single-use, expires after fifteen minutes, and belongs to one
  subject and one conversation. Answering somebody else's is refused, and refused
  as "unknown" rather than "not yours" - saying otherwise would confirm it exists.

`CANCEL cfm-…` consumes the ticket too, so "no" cannot become "not yet".

The facts in each ticket come from the wiki, which is untrusted content, so they
are contained: one line each, long ones cut, and a page title may not display
something that looks like a ticket reference.

## Conversation state

One runtime is kept per `(authenticated subject, conversation)`. The subject
comes first deliberately: a conversation identifier is a routing handle supplied
by the caller, so on its own it selects nothing.

On this agent the isolation is doubled, because LangGraph keys its persisted
state by `thread_id`. Using the caller's identifier directly would let somebody
resume another person's conversation by guessing a string, so `thread_id_of()`
hashes the authenticated subject *together with* the conversation - the half a
caller controls is only ever half.

State is bounded and expires, and eviction closes the MCP session the runtime
holds. Against a real Confluence that matters: a process that exits without
closing them leaves sessions looking active long after they are not.

> Each conversation gets its own `InMemorySaver`. That is right for a
> proof of concept - one runtime per conversation, closed on eviction - but a
> deployment that must survive a restart wants a durable checkpointer instead.

## Acting on behalf of the caller

Over the `mcp-atlassian-http` binding the agent sends an `Authorization` header
per request, and the server builds a Confluence client for whoever it names. That
is what makes the agent respect the page and space restrictions of the person
asking instead of quietly reading around them.

**The proof of concept does not yet mint that credential per caller.** It reads
`WIKI_MCP_USER_ACCOUNT` and `WIKI_MCP_USER_SECRET` from the environment, so an
HTTP deployment authenticates its callers correctly but still reaches Confluence
as one configured account. Closing that gap means exchanging the caller's token
for an on-behalf-of credential; only the `WikiUserCredentials` implementation
changes, and nothing above the MCP boundary notices.

Until then, treat the multi-user HTTP mode as authenticated but not yet
per-caller *at the wiki*.

## What the installed runtime supports

| Capability | Without it |
|---|---|
| OpenAI-shaped non-streaming responses | An OpenAI client cannot read a reply |
| Request header forwarding | Every discussion of one caller shares a session |

`tests/contract/test_wiki_openai_http_surface.py` probes the installed library at
import time rather than pinning a version, so the suite tells the truth against
both the published release and a linked checkout, and starts enforcing each
contract the moment it becomes available.
