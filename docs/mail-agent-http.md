# Serving the Mail Agent over HTTP

The command line drives one person's mailbox. Serving the agent over HTTP is what
lets LibreChat talk to it, and later what lets an aggregator agent call it.

Two things change, and only two: the caller is established by the transport
instead of by `.env`, and a confirmation can no longer block a turn.

## What runs the HTTP surface

Routes, OpenAI request shapes, JWT validation and discovery come from
[`ygo74-agent-runtime`](https://github.com/ygo74/ai-enterprise-agent-runtime). We
do not reimplement them.

The composition root uses the runtime's fluent `HostingFactory`: it registers
the Mail entrypoint and descriptor, exposes Chat Completions, applies exactly
one authentication policy, then enables authenticated model discovery. An
OIDC issuer selects JWT validation and takes precedence over the demonstration
API key; set `MAIL_AGENT_HTTP_JWKS_URL` when the issuer's JWKS endpoint is not
discoverable or to avoid discovery during startup. OIDC clients send
`Authorization: Bearer <token>`.

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
| `MAIL_AGENT_HTTP_JWKS_URL` | Optional explicit JWKS endpoint; otherwise resolved from OIDC discovery. |
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

The actual key also includes the operator identity namespace and verified email,
display name and roles. Refreshed claims, expiration, eviction or an invalidated
run select fresh resources even if `X-Conversation-Id` is unchanged. Do not remove
claim partitioning to preserve stale authorization.

### Mail provider continuity and controlled LibreChat replay

Mail's `MailAgentSession` HTTP/console adapter deliberately requires provider
continuation for its real `OpenAIChatClient` (direct OpenAI or Azure route).
It retains the provider's storage defaults: no
`store=False`, duplicated local memory or client-history replay is introduced.
Scripted/local BYOA clients retain their existing profile. Runtime routing ID and
provider `service_session_id` are distinct; the installed adapter 1.14.2/core
1.18 uses Responses and maps provider `resp_`/`conv_` IDs to `previous_response_id`/
`conversation`. Missing/stale continuation fails explicitly, not silently as an
apparently context-free successful turn.

See the runtime's `docs/python/native-agents.md` for the three safe INFO events,
their structural fields and process-local fingerprints. Export only those added
records/fields through your configured standard logging sink. A plain console
formatter may omit the extra fields. Never turn on global DEBUG: older application
debug logs and third-party SDK logs are not this diagnostic allowlist.

**Proven deterministic regression:** FastAPI's normal streamed completion closed
`HttpConversationEngine.stream` while it was still inside `cache.turn`.
`GeneratorExit` invalidated a successful session; the same header's next request
created fresh state. The runtime now releases the completed turn before emitting
the terminal. Actual HTTP plus installed SDK mocked-transport tests verify
normal/stream/mixed continuation, tools and approval/refusal, without live mail.
This does **not** establish the original live exchange's cause or prove that a
real model will interpret the follow-up correctly.

**Completed safe functional replay (2026-10-10):**
`test_title_free_sdk_http_followup_reuses_bounded_table_and_exact_tickets` drives
the real authenticated FastAPI routes and JSON/SSE projectors with two complete
LibreChat-shaped message arrays and a stable `X-Conversation-Id`. The installed
MAF/OpenAI SDK uses a mocked HTTP Responses provider with a continuation store.
Its deterministic decision logic reads retrieved fixture results, produces a
table, then derives follow-up tool arguments **from that stored table**; a
negative control without prior scope asks for a selection and emits no calls.
This is not a canned second reply and is not live inference.

The fixture re-dates copies of the existing synthetic sample mailbox: 15 messages
across all seven UTC days, 04/10/2026 through 10/10/2026, plus two out-of-period
sentinels. One bounded search and one existing-category listing produce 10
applicable proposals and five uncertain messages. All four stream/non-stream
combinations verify the same 10 exact message/category tickets, no modified
messages, no widening/retrieval on follow-up, no duplicated client history, and
the four actual provider calls' chain `resp_scope_1` → `resp_scope_2` →
`resp_scope_3` → `resp_scope_4`. Only the two business HTTP requests are submitted;
no title request or real LibreChat process participates.

This replay also exposed a second, independently proven defect: SDK middleware
dispatches parallel approval requests one by one, with no provider call or token
usage on intermediate approval-only rounds. The binding previously rejected
these as missing provider usage. It now excludes only instrumented, provider-free
approval-only dispatch from accounting; actual provider usage gaps still fail.
Runtime tests cover three parallel approvals, approval/refusal, bounded cleanup and both modes,
checking exact genuine token totals and the next turn's continuation.

**Safe availability observation (2026-10-10):** LibreChat responds on localhost
3080. Its container mounts
`C:\devel\searchbot\research\librechat\librechat.yaml`, not `deploy\librechat.yaml`.
The mounted Mail entry already has `titleConvo: false`, a conversation header and
port 8002; Mail readiness on localhost 8002 returns 200. No active configuration
was modified, credentials read or mailbox operation invoked. Mounted-file
metadata does not prove when the running LibreChat process loaded that setting.
No authenticated two-turn live reproduction was performed.

Controlled test procedure (operator/user action, not an automatic mailbox test):

1. Confirm the **effective mounted configuration** and loaded settings of the
   LibreChat instance under test. Use a dedicated test deployment, copying
   `deploy\librechat-mail-continuity-test.yaml` as its configuration. It deliberately
   disables titles only for the test endpoint, targets a host mock-mail worker on
   8123, and uses a key placeholder. Do not overwrite the active deployment.
   Set the key through your normal test environment, not in source.
2. Link the runtime checkout as above, then start the mock-mail worker with the
   existing run command and your normal provider configuration. Restart **before**
   the scenario to load changes, never between its two turns. Ensure controlled
   test data contain 15 authorized messages dated 04/10/2026 through 10/10/2026
   and known existing categories; otherwise record the actual fixture count.
   Do not switch to a real mailbox just to make the fixture count match.
3. In a new LibreChat discussion, send:
   `Nous sommes le 10/10/2026. Analyse les mails du 04/10/2026 au 10/10/2026
   inclus et propose leur classement dans les catégories existantes, en tableaux.
   N'effectue aucune modification.`
   Then, without restarting/changing caller/conversation, send:
   `peux tu classer les mails dans les categories existantes`.
   Do not submit any confirmation commands during this diagnostic pass.
4. Compare safe logs: same identity/conversation fingerprint, cache create then
   hit, same binding instance, turn 1 then 2; last completed provider fingerprint
   must equal the next provider-request fingerprint. Include all tool/approval
   subcalls and any extra HTTP requests. A failed/expired/recreated chain must
   have an explicit diagnostic, not silent context reset.
5. Check the answer/tickets only reference the first turn's selection and known
   category IDs. No widened scope or unnecessary fresh-scope question; messages
   with no suitable existing category stay unclassified; no write before normal
   confirmation/authorization. A scripted model is not semantic evidence.
6. If isolating titles remains necessary, repeat in a separate fresh test
   conversation with `titleConvo: true` on that **test endpoint only**, reload
   LibreChat before replay, and compare request/subcall ordering. Restore the
   isolated test setting afterwards. Never infer title interference from the
   response text or heuristically classify title prompts by their content.

Safe implementation/functional validation is complete without accessing a live
mailbox, credentials or shared services. An authenticated real LibreChat/model
replay remains an **optional, out-of-environment acceptance check**, not a claimed
result of these tests. Original historic cause, real-model interpretation and
title interference remain unproven without corresponding live evidence; the
historic exchange cannot be retroactively attributed to either reproduced defect.

Targeted verification uses the existing `.venvs\mail-agent-maf\Scripts\python.exe`:
`-m pytest` on the runtime's `test_provider_continuity.py`,
`test_agentframework_binding.py`, `test_native_worker.py`,
`test_conversation_cache.py`, `test_serialized_conversation_lifecycle.py`,
`test_agent_conversation.py`, `test_conversation_payloads.py` (all under
`tests\integration\python`) and the lab's `tests\contract\test_openai_http_surface.py`
and `tests\integration\test_conversation_engine.py`: **177 passed** (including the
five new lab functional/negative controls and eight runtime parallel-approval cases).
The provider double lives in `tests\support\mail_continuity_provider.py` and uses
only controlled fixtures; no worker/listener was started and no live endpoint
was called for this replay.
Targeted `-m ruff check` passes under each repository's existing rules.
`-m mypy --strict --explicit-package-bases --follow-imports=silent` passes on the
six changed runtime production modules; the lab's existing mypy configuration
passes on `MailAgentSession`. For editable namespace resolution, set `MYPYPATH`
to the runtime checkout's `packages\python\agents`, `packages\python\agentframework`
and `packages\python\security` directories, separated by `;` on Windows.

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
holds. `ConversationRuntimeCache` leases the application-created conversation;
the runtime's generic `HttpConversationEngine` handles confirmation commands
before the agent session and adds pending ticket details to the shared reply.
The Mail factory, runtime composition and Microsoft Agent Framework session
adapter remain application code.

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
