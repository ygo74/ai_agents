# Serving the Mail Agent over HTTP

The command line drives one person's mailbox. Serving the agent over HTTP is what
lets LibreChat talk to it, and later what lets an aggregator agent call it.

Two things change, and only two: the caller is established by the transport
instead of by `.env`, and a confirmation can no longer block a turn.

## What runs the HTTP surface

Routes, OpenAI request shapes, JWT validation and discovery come from
[`ygo74-agent-runtime`](https://github.com/ygo74/ai-enterprise-agent-runtime). We
do not reimplement them.

What this repository owns is what that library deliberately leaves to the
application - the same split Microsoft describes for its own hosting helpers:

| Owned by the runtime library | Owned here |
|---|---|
| `POST /v1/chat/completions`, `GET /v1/models` | Which caller a request is attributed to |
| OpenAI payload normalisation | Which conversation it continues |
| JWT / API-key authentication | What happens to a gated operation |
| Discovery and access policy | Isolation and eviction of conversation state |

## Running it

```powershell
$env:MAIL_AGENT_MODE = "mock"
$env:MAIL_AGENT_HTTP_API_KEY = "demo-key"
.\.venvs\mail-agent-maf\Scripts\python.exe -m uvicorn `
  "ai_agent_lab.mail.application.entrypoints.service:build_app" --factory --port 8123
```

```powershell
curl -Method POST http://127.0.0.1:8123/v1/chat/completions `
  -Headers @{"x-api-key" = "demo-key"} `
  -Body '{"model":"mail-agent","messages":[{"role":"user","content":"anything from John?"}]}'
```

VS Code has a `Mail Agent API (debug, reload)` configuration that does the same on
port 8123 with the debugger attached.

### Developing against a runtime checkout

The serving library is developed alongside this repository, so publishing a
release to try a fix is a slow way to discover it was the wrong fix. Link a
working copy instead:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m scripts.install `
  --runtime-source C:\devel\ai-enterprise-agent-runtime
```

An edit in that checkout is then live here, with no reinstall. The dependency is
declared as a range rather than an exact pin for exactly this reason: an exact
pin would make pip replace the working copy with the published wheel the next
time anything is installed.

`pip install --editable <checkout>\packages\python` does the same thing by hand;
the flag exists so the ordering is right, since the link has to be in place
before the distribution that requires it.

To go back to the published release:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m pip install --force-reinstall ygo74-agent-runtime
```

The test suite reports which one it ran against: the contract tests probe the
installed library and skip, with a reason, whatever it cannot do yet.

### Settings

| Variable | Meaning |
|---|---|
| `MAIL_AGENT_HTTP_API_KEY` | One key, one caller. For demonstrations only. |
| `MAIL_AGENT_HTTP_OIDC_ISSUER` | Keycloak realm URL. Once set, the API key is ignored. |
| `MAIL_AGENT_HTTP_OIDC_AUDIENCE` | Audience the token must carry. Default `mail-agent`. |
| `MAIL_AGENT_HTTP_ROLES_CLAIM_PATH` | Where roles live in the token. Default `realm_access.roles`. |
| `MAIL_AGENT_HTTP_MAX_CONVERSATIONS` | Ceiling on live conversations. Default 200. |
| `MAIL_AGENT_HTTP_IDLE_MINUTES` | How long an untouched conversation is kept. Default 30. |

The service never runs unauthenticated. Without a subject there is nothing to
partition state by, so a mailbox could not be told from another.

## Confirmations, without a side channel

At a console the agent asks and waits. An HTTP request must be answered, so a
gated operation ends its turn **unperformed** and comes back as a ticket:

```text
> file the Project Alpha message under Finance

I have asked for confirmation.

Awaiting your confirmation - nothing has been changed yet:

- **Apply this label to the message?**
  - Message: m-alpha-1
  - Subject: Project Alpha - architecture review
  - From: john.smith@example.com
  - Label: Finance (FINANCE)
  - Reply `CONFIRM cfm-1a2b3c4d5e6f` to approve, `CANCEL cfm-1a2b3c4d5e6f` to decline.

> CONFIRM cfm-1a2b3c4d5e6f

apply_label succeeded.
```

Each ticket carries the facts the presenter resolved for it - the subject, the
sender, the label's name rather than its identifier - because a chat reply is
read long after the message it refers to has scrolled away. A bare list of
identifiers would make the reader go back up the conversation to work out what
they are approving, which is how people approve things they have not read.

Those facts are written by the application, from the very request that will
authorise the operation, so what is read is what gets executed and audited. They
come from mail, so they are contained: one line each, long ones cut, and a
subject may not display something that looks like a ticket reference.

Why this is not a weakening of the console behaviour:

- the first turn declines every suspended call, so nothing runs while it is only
  described;
- the ticket stores the **exact arguments**, and confirming re-invokes the
  capability from them - the model plays no part in the second turn and cannot
  change what was described;
- `CONFIRM` is read by a literal parser *before* the model sees the message, so a
  model can never approve anything, and a sentence merely mentioning a ticket is
  an ordinary question. Markdown decoration around the whole command is accepted,
  since that is what a copied answer looks like, but a sentence quoting one still
  matches nothing;
- a ticket is single-use, expires after fifteen minutes, and belongs to one
  subject and one conversation. Answering somebody else's is refused, and refused
  as "unknown" rather than "not yours" - saying otherwise would confirm it exists.

`CANCEL cfm-…` consumes the ticket too, so "no" cannot become "not yet".

## Conversation state

One runtime is kept per `(authenticated subject, conversation)`. The subject
comes first deliberately: a conversation identifier is a routing handle supplied
by the caller, so on its own it selects nothing. Two people quoting the same
identifier get their own conversation.

LibreChat sends the identifier as a header, because the OpenAI schema has no
field for one. The runtime carries an allowlist of headers into
`metadata["headers"]` and promotes the conversation one to
`metadata["conversation_id"]`; the agent reads that, and falls back to a
per-subject default when neither is present. Falling back is safe - the
identifier only selects state *within* an authenticated subject - but it does
mean a caller's discussions share one conversation until the header arrives.

Credentials are never among the forwarded headers: `authorization`, `x-api-key`
and friends are refused when the endpoints are registered, so a misconfiguration
fails at startup rather than leaking a token into a handler, a log or a prompt.

State is bounded and expires, and eviction closes the MCP session the runtime
holds. Microsoft's Python hosting helpers ship a session store that is
process-local with no eviction, and .NET's per-principal isolation has no Python
equivalent; `ConversationRuntimeCache` is that missing piece, written without any
knowledge of mail so it can be contributed upstream.

## What the installed runtime supports

Two capabilities arrived after the first release, and both were contributed
upstream rather than worked around here:

| Capability | Released in | Without it |
|---|---|---|
| OpenAI-shaped non-streaming responses | 0.0.3 | An OpenAI client cannot read a reply, though it can follow a stream |
| Request header forwarding | linked checkout | Every discussion of one caller shares a session |

`tests/contract/test_openai_http_surface.py` probes the installed library at
import time rather than pinning a version, so the suite tells the truth against
either a published release or a linked checkout: what the runtime cannot do yet
is skipped with an explicit reason instead of passing quietly.

## LibreChat

```yaml
endpoints:
  custom:
    - name: 'mail-agent'
      apiKey: '${MAIL_AGENT_HTTP_API_KEY}'
      baseURL: 'http://mail-agent:8123/v1'
      models:
        default: ['mail-agent']
        fetch: false
      headers:
        x-api-key: '${MAIL_AGENT_HTTP_API_KEY}'
        X-Conversation-Id: '{{LIBRECHAT_BODY_CONVERSATIONID}}'
```

Three settings to avoid:

- `directEndpoint: true` bypasses the SDK and posts to the literal base URL;
- `baseURL: user_provided` makes LibreChat strip **every** configured header,
  including the one carrying the credential;
- enabling web search flips the request to the Responses API, which this endpoint
  does not serve.

With Keycloak, replace the key with the forwarded token - LibreChat needs
`OPENID_REUSE_TOKENS=true` for the placeholder to resolve:

```yaml
      headers:
        Authorization: '{{LIBRECHAT_OPENID_ACCESS_TOKEN}}'
        X-Conversation-Id: '{{LIBRECHAT_BODY_CONVERSATIONID}}'
```

The conversation identifier is read from `metadata["conversation_id"]` first and
from the forwarded header otherwise, so a client that names a conversation in the
body keeps control of it whatever a proxy adds.
