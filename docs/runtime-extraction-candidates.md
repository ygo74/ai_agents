# What could move to `ygo74-agent-runtime`

> **Status, 2026-09-12.** Batches 1 to 5 of the sequencing table below have been
> delivered: the security spine, the identity projection, the conversation port
> and payloads, and the capability registry now live in `ygo74-agent-runtime`
> 0.0.4 and have been deleted from this repository. See
> [architecture.md](./architecture.md#10-what-this-repository-no-longer-owns) for
> what that changed here, and `docs/parity-status.md` in the runtime for the
> .NET and Java debt it created. The rest of this document is unchanged and
> describes the remaining work.
>
> Three corrections were forced by the delivery and are folded in below:
> the capability registry could not move without the security spine, `py.typed`
> turned out to be load-bearing, and the moved error base broke every boundary
> that rendered a refusal.

This is an **analysis**, not a migration. It records which parts of this repository belong to the
hosting library rather than to the agent laboratory, and what each one would need before it could move.

The target is `ygo74-agent-runtime` (Python package `ygo74.agent_runtime`), which already owns the
OpenAI and Anthropic endpoints (`domains.endpoints`), discovery and the agent descriptor
(`domains.discovery`), JWT and API-key authentication (`domains.auth`), routing (`routing`), the
middleware pipeline (`middleware`) and the beginnings of observability (`observability`).

Nothing is decided here. Nothing moves until the sequencing table is agreed.

## Why the question arises

Three independent observations point the same way.

### 1. The two agents duplicate their scaffolding

The Mail Agent and the Wiki Agent were written separately and converged on the same modules. The table
counts lines that are byte-for-byte identical between the two copies of one module.

| Module | mail | wiki | identical lines | similarity |
|---|---|---|---|---|
| `config/http_settings.py` | 58 | 68 | 49 | 78 % |
| `skills/gating.py` | 177 | 137 | 107 | 68 % |
| `application/entrypoints/conversation.py` | 236 | 175 | 136 | 66 % |
| `mcp/binding.py` | 283 | 316 | 183 | 61 % |
| `mcp/connection.py` | 174 | 188 | 108 | 60 % |
| `application/entrypoints/service.py` | 201 | 204 | 121 | 60 % |
| `application/entrypoints/http.py` | 124 | 101 | 67 | 60 % |
| `security_floor.py` | 27 | 47 | 19 | 51 % |
| `catalog.py` | 205 | 218 | 106 | 50 % |
| `inmemory/draft_store.py` | 53 | 33 | 21 | 49 % |
| `mcp/dialects.py` | 104 | 123 | 49 | 43 % |
| `application/composition.py` | 394 | 414 | 169 | 42 % |

The measure **understates** the kinship. It compares literal lines, and the Mail Agent has just been
instrumented with logging calls the Wiki Agent does not have yet. The classes, their methods and the
order of their steps are the same; only the domain name and the error type differ.

Drift has already started, which is the strongest argument in the table.

- The Wiki Agent's `entrypoints/service.py` refuses to start without an identity
  (`_refuse_an_open_service`, line 82) and enables JWT validation. The Mail Agent's has no such guard,
  and its JWT validation is commented out (`entrypoints/service.py:92-95`). A security property present
  in one copy is absent from the other.
- The Wiki Agent's `mcp/binding.py` withdraws every write capability when the server is deployed
  read-only (`capabilities_in`, lines 158-182). The Mail Agent's binding has no equivalent.

That is the normal failure mode of duplicated code, and it is happening on the security path.

### 2. Some of the code already states where it belongs

`core/serving/runtimes.py` says in its own docstring that it is *"written without knowing anything
about mail so it can serve any agent - and be contributed upstream"*. The component was designed as a
contribution to the library; it simply has not moved yet.

### 3. The contract is inverted at the boundary

The runtime builds a typed authentication context (`AuthenticatedUserContext`), flattens it with
`to_dict()`, and `add_ai_endpoints` hands the application a `dict`. This repository then re-parses that
dictionary in `core/security/principal.py` and `core/serving/payloads.py` to rebuild a typed model.

The application therefore reconstructs a type the library already had and deliberately discarded. Every
application that plugs into the runtime will redo that work, and each will write it slightly
differently. That is a gap in the contract, not a choice of this repository.

## Eligibility criteria

A component belongs to the library when it meets all five.

1. **No business knowledge.** It does not know what a message, a documentation space or an issue is. A
   closed enumeration listing business values disqualifies a component until the enumeration is opened.
2. **Duplicated, or bound to be.** Present in both agents, or unavoidable for the third.
3. **Stable contract.** The signature is dictated by an external protocol (OpenAI, MCP, OAuth) or by a
   security property, not by local convenience.
4. **No agentic framework dependency.** Neither Microsoft Agent Framework, nor LangChain, nor CrewAI.
   This one is already checked mechanically by `tests/architecture/test_distribution_boundaries.py`.
5. **A stated parity position.** Either the component transposes to .NET and Java, or it is declared
   Python-first knowingly.

A component failing criterion 1 or 4 stays here. A component failing only criterion 5 may move,
provided the status is written down.

A sixth consideration applies to anything already working here: **a defect that is tolerable in a
laboratory is not tolerable in a library.** This repository runs one process, one deployment, and
conservative settings. A component published for others will be configured aggressively and deployed
across workers. Several candidates below are correct *here* and would be incorrect *there*; those are
marked as such rather than hidden.

## Tier 1 - ready to move

No generalisation beyond a parameter or two, and no known defect.

### Payload reading and reply rendering

*Source: `agents/core/src/ai_agent_lab/core/serving/payloads.py` · Target: `domains/endpoints/` · portable*

`ConversationPayloadReader` turns the dictionary handed over by `add_ai_endpoints` into a typed model;
`AgentReplyRenderer` makes the return trip; `latest_message` extracts the last user turn while
tolerating both content shapes of the OpenAI schema (a string, or a list of content parts).

This is the direct counterpart of observation 3: the module reads a shape the library itself produced.

It also carries a constant that is already duplicated: `CONVERSATION_HEADER = "x-conversation-id"` here,
`DEFAULT_CONVERSATION_HEADER = "x-conversation-id"` in
`ygo74.agent_runtime.domains.endpoints.header_forwarding`. Two definitions of one header, only one of
which can be authoritative.

### Typed reading of the authentication context

*Source: `agents/core/src/ai_agent_lab/core/security/principal.py` · Target: `domains/auth/` · portable*

`Principal.from_auth_context` is the inverse of `AuthenticatedUserContext.to_dict()`. It enforces a rule
with nothing mail-specific about it: the subject comes from the verified token, never from the request
body, and a missing subject is a refusal to serve rather than a fallback to an anonymous identity.

The `require_email` flag is the right abstraction and deserves to move up. A mailbox is addressed by
e-mail; a wiki account is not. An identity model should neither force an address on agents that have
none, nor let a mail agent guess whose mailbox to serve.

**The generalisation is not "use the runtime's identity type instead".** `Principal` is frozen and
rejects an empty subject; `UserIdentity` and `AuthenticatedUserContext` are mutable dataclasses that
allow `subject=None` and carry an arbitrary claims dictionary. Substituting one for the other would put
a mutable identity into a state cache keyed by that identity, and would hand raw token claims to
application code that has no business reading them.

What should move is an **immutable, validated projection**: a canonical subject, the profile fields an
application is allowed to see, and nothing else. The right place to build it is inside the runtime,
handed to the entrypoint directly, which removes the dictionary round-trip rather than relocating it.

### The conversation port

*Source: `agents/core/src/ai_agent_lab/core/serving/conversation.py` · Target: `domains/contracts/` · portable*

`ConversationTurn`, `AgentReply` and the `ConversationEngine` protocol. A turn goes in, a reply comes
out. This is the minimal seam between a transport and an agent, and it is exactly what keeps the
framework comparison honest: identity, transport and session isolation are written once.

`AgentReply.pending_confirmations` is the only concession, and it is justified: a reply must be able to
say that something was described without being executed. Empty means "nothing is waiting", never
"everything succeeded".

The runtime already has `UseCaseHandler`, but its signature is synchronous and untyped (`input: Any`).
This port is the next step up.

### Capability registry contract

*Sources: `core/registry.py`, `core/manifests.py` · Target: `domains/contracts/` · portable*

`SkillRegistry` and `SkillDescriptor` are what an orchestrator needs to build its own tools: a name, a
description, an argument schema, the security posture and the coroutine that runs the capability. All
three frameworks read this same registry, which is what keeps the capabilities from being ported three
times.

Only the typed contract is in scope. **Loading** the YAML packages (`core/config/manifests.py`,
`core/config/directory.py`) is a convention of this repository and stays here.

It is listed in Tier 1 because nothing has to change for it to move, and it is sequenced early because
the human-approval domain depends on it.

## Tier 2 - high value, generalisation or repair required

### `ConversationRuntimeCache`

*Source: `agents/core/src/ai_agent_lab/core/serving/runtimes.py` · Target: `domains/sessions/` · Python-first*

Holds one conversation's state between two HTTP requests, keyed by the **authenticated subject first**
and the conversation identifier second. A caller supplying somebody else's conversation identifier gets
their own. Entries expire, the cache is bounded, and eviction closes the MCP session the entry held.

The design is right and the three risks it names - identity confusion, unbounded growth, dangling
resources - are the right three. Its docstring already aims at the library.

**It is not ready to move as is.** Two defects are invisible at this repository's settings and would
surface immediately under a library's:

- **No lease.** `acquire` returns a runtime and forgets about it. A later `acquire` runs `_expire` and
  `_enforce_bound`, either of which may close an entry that an in-flight request is still using -
  `_enforce_bound` evicts the least recently used entry without asking whether anyone holds it. Both
  conversation engines keep using the runtime after acquiring it. At 200 conversations and a 30-minute
  idle lifetime this is improbable; at the bounds somebody else will configure, it is not.
- **Closing under the global lock.** `_expire` is awaited from inside `async with self._lock`, and it
  awaits `self._closer`, which closes an MCP session over the network. One unresponsive server stalls
  every conversation in the process.

Fix before extraction: reference-count or lease entries and never close one in use; remove entries
under the lock but await builds and closers outside it; add tests covering eviction and expiry racing
with an in-flight request.

Separate blocker: the class uses PEP 695 generic syntax (`class ConversationRuntimeCache[RuntimeT]`),
available from Python 3.12, while the runtime declares `requires-python >= 3.11`. Rewrite with
`TypeVar` or raise the floor.

### Human approval over a stateless API

*Sources: `core/security/tickets.py`, `core/security/confirmation.py`, `core/security/commands.py`,
`core/security/broker.py`, `core/security/ledger.py`, `core/security/unattended.py`,
`core/serving/confirmations.py`, `core/serving/pending.py` · Target: a new `domains/humanapproval/` · portable*

**This is the most reusable asset in the repository.** The runtime has an *example* called
`04-human-in-the-loop`; it has no human-approval *domain*.

The problem solved is not business-specific: an OpenAI-compatible API answers every request, so a turn
cannot hold while a person decides.

- **`ConfirmationTicket`** stores what the person read **and the exact arguments** the operation will
  run with. Replaying a ticket re-invokes the capability from the stored arguments, never from what the
  model says the second time. The model describes the operation and then plays no part in running it,
  so it cannot alter it in between.
- Four properties are enforced **when a ticket is claimed**, not when it is issued: it belongs to one
  subject, it belongs to one conversation, it can be claimed once, and it expires. A ticket identifier
  authorises nothing on its own.
- **`ConfirmationCommandParser`** reads `CONFIRM cfm-xxxx` **before** the model sees the turn. An
  approval that reached the model first would be an approval the model could reinterpret. The grammar is
  deliberately tiny: no attempt to understand "yes go ahead". The single concession is markdown
  decoration, because a chat surface renders the instruction as code and the user copies it back with
  its backticks.
- **`ConfirmationPolicy`** is deterministic and data-driven, with an explicit precedence:
  per-user `always_confirm`, then per-user `auto_approve`, then the descriptor default - and above all of
  that, the security floor, and only the floor.
- **`ConfirmationBroker`** decides whether to reuse the answer already in the ledger or to ask the
  authority. Reusing the recorded request rather than minting a fresh one is what makes the audit trail
  refer to the confirmation a human actually granted. It must move with the rest: leaving it behind
  would leave the correctness of the whole mechanism outside the domain that claims to own it.
- **`UnattendedApprovalAuthority`** always refuses. Reaching it means a capability was gated by the
  policy but was not suspended by the framework; refusing keeps a registration mistake from becoming an
  unattended write.
- **`PendingConfirmationRenderer`** contains what it displays: one line per fact, truncation, and
  **redaction of any ticket reference found in third-party content**. A retrieved page therefore cannot
  imitate the application asking for an approval.

Two things must be settled before extraction.

- **Decouple the runner.** `ConfirmedOperationRunner` depends on `SkillRegistry` and `ResultRenderer`.
  Two ports - "find the capability by name" and "render its result" - would free it from this
  repository's registry.
- **State the storage contract honestly.** `InMemoryPendingConfirmationStore` says in its own docstring
  that it holds one process, "which is the whole lifetime of the PoC". That is true here and false for a
  library: behind two workers, a ticket issued on one is unclaimable on the other, and a restart loses
  every pending approval. Extract the `PendingConfirmationStore` protocol and keep the in-memory class
  as the test adapter, but do not advertise the domain as production-ready without an atomic shared
  store.

### Gated operation runner

*Sources: `mail/skills/gating.py`, `wiki/skills/gating.py` · Target: `domains/humanapproval/` · portable*

68 % identical, and it is the security path itself: permission check, confirmation policy, execution,
audit record. Both agents state in their docstring that this exists "so that no write skill can forget a
step, and so that adding a new write capability cannot introduce a different, weaker path". That
argument applies once more, one level up: a copy per agent is one copy away from a weaker path, and
there are already two copies.

The parameterisation is thin - a tool enumeration and an operations catalogue - and both reduce to the
`ToolOperationDescriptor` the runner actually consults. A generic runner taking the descriptor directly
removes the duplication without touching either domain.

This candidate was not obvious from the module names and is the strongest one the duplication table
surfaced.

### Security posture primitives

*Sources: `core/security/operations.py`, `core/security/floor.py`, `core/security/permissions.py`,
`core/security/context.py`, `core/security/audit.py`, `core/observability/audit.py` ·
Target: `domains/security/` · portable*

These modules encode the contract this repository's instructions impose on every tool: operation type,
risk level, required permission, confirmation required by default.

- **`ToolOperationDescriptor`** is the input of the confirmation policy. It is data decided in code; the
  model never contributes to it.
- **`SecurityFloor`** separates two questions that are easily conflated: the risk level says *how much*
  an operation costs, the floor says *what a configuration may not touch*. A configuration below the
  floor is refused at load time rather than silently corrected - a control that repairs itself in
  silence teaches nobody that the configuration was wrong.
- **`Permission`** is declared by the domain that owns it, never by a central list, so a new agent does
  not force a change in a shared enumeration. That property must survive the move: the library provides
  `PermissionRegistry`, not the catalogue of permissions.
- **`AuditRecord`** carries identifiers and outcomes only - no message body, no recipient list, no
  credential.

This is also the most direct answer to the fact that the runtime's `observability/otel.py` is still a
stub: the audit trail is the first signal an enterprise library has to produce.

### Untrusted content and prompt fencing

*Sources: `core/security/untrusted.py`, `core/security/fencing.py`, `core/reasoning/envelope.py`,
and `ReasoningRequest` from `core/reasoning/ports.py` · Target: `domains/security/` · portable*

`UntrustedText` puts "this came from a third party" into the type system. The raw value is reachable
only through `expose()`, which makes every dereference greppable in review, and its `repr` hides the
payload so accidental logging cannot leak it.

`UntrustedFence` adds a unique, unguessable delimiter per rendering, neutralises any delimiter found
inside the content, and states explicitly that the block is data. The contract names the source, and
that is not decoration: a model told it is reading a mailbox and handed wiki pages has been given a
false premise about its own input.

**Blocker.** `UntrustedOrigin` is a closed enumeration listing `MAIL_BODY`, `WIKI_PAGE_TITLE` and eleven
other business values. As it stands the component fails criterion 1. The origin must be opened - a free
string, or an enumeration extensible by the calling domain - before anything moves.

**Coupling to watch.** `reasoning/envelope.py` renders a `ReasoningRequest`, which lives in
`reasoning/ports.py` and itself holds `UntrustedText`. The request and section models must travel with
the fence; only the `TextReasoner` protocol stays behind, with the framework adapters that implement it.

### Tokens

*Source: `core/security/tokens.py` · Target: `domains/auth/` · portable*

Three rules, all of them security properties:

- `AccessToken` has a redacted `repr`, so an accidental f-string leaks nothing;
- `DelegatedTokenSource` exists so the agent **exchanges** a token instead of relaying it. The MCP
  specification forbids passthrough and requires a server to check that a token was issued for it, which
  it cannot do if the agent forwards the one the client sent;
- verification produces an identity and nothing else.

The module holds ports only. Its natural home is beside `JwtAuthenticator`, which it completes: the
runtime can validate an incoming token today, but cannot obtain one for the next hop.

It depends on the identity projection, so it cannot move before it.

### An agent's HTTP settings

*Source: `agents/mail/.../config/http_settings.py` and `agents/wiki/.../config/http_settings.py` ·
Target: `domains/configuration/` · portable*

78 % identical lines, and both declare the same things: demonstration API key, OIDC issuer, audience,
JWKS URL derivation, roles claim path, conversation bound, idle lifetime. The runtime already supplies
the `JwtValidationConfig` and `JwksKeyResolver` these settings feed, and already has
`domains/configuration/models.py` to host them.

Three points stop this being a Tier 1 rename.

- The classes have **already diverged beyond the prefix**: the Wiki Agent adds `uses_oidc`, which is
  what its start-up guard consults, and the Mail Agent has nothing equivalent.
- Both derive the JWKS URL as `<issuer>/protocol/openid-connect/certs`, which is **Keycloak's layout**,
  not a standard. A library must read the issuer's discovery document, or require the URL.
- The runtime depends on `pydantic`, `typing-extensions` and `PyJWT` only. These settings classes are
  `pydantic-settings`, so moving them is also a decision about which configuration library the runtime
  imposes on its hosts.

### Descriptor factory

*Source: `agents/core/src/ai_agent_lab/core/serving/discovery.py` · Target: `domains/discovery/` · portable*

Builds the `AgentDescriptor` published through discovery from the agent's manifest, so that what a
caller discovers cannot drift from what the agent actually does.

The stated justification does not yet hold, and that has to be fixed rather than moved. The factory
hard-codes `security_schemes=("jwt", "oidc")` while both services also accept an API key, and leaves
`tool_invocation` at its default of `False` while every agent here exposes tools. Discovery is already
describing something other than reality.

The right shape on the library side is a factory fed by a minimal protocol - name, description, list of
capabilities - **and by the endpoint and authentication configuration actually in force**, so the
descriptor is derived from the deployment rather than asserted alongside it. The runtime already has
`DescriptorDefaults` and `DescriptorBinding` next door, and `EndpointConfiguration` in
`domains/configuration/` carries exactly the facts the descriptor is currently guessing.

### MCP client plumbing

*Sources: `*/mcp/connection.py`, `*/mcp/binding.py`, `*/mcp/dialects.py`, `mail/mcp/oauth.py` ·
Target: a new `domains/mcp/` · **Python-first** (depends on the `mcp` SDK)*

This is the candidate whose boundary needs the most care, because the four modules are **not** uniformly
domain-free. What moves is the mechanism; what stays is every place a domain is named.

**Moves.**

- **Transport lifecycle** (`McpConnection`). One session for the lifetime of a conversation. The lock is
  not an optimisation: a model routinely calls two tools in the same turn, the framework runs them
  concurrently, and without a guard each opens its own transport. The losers are then collected from
  another task, anyio refuses to unwind a cancel scope outside the task that entered it, and the visible
  symptom is not a warning - the transport dies mid-turn. That trap is worth solving once, in the
  library. Only the error type raised needs parameterising.
- **Binding schema and loading.** How a deployed server declares its transport, its capabilities and the
  name it gives each tool, and the rule that anything undeclared is never offered to the model rather
  than failing on the first call.
- **Registry mechanics.** Explicit registration, refusal to silently replace, and naming the
  alternatives when a dialect is unknown.

**Stays.**

- The **capability enumerations and catalogues**. The Mail binding is typed on `MailToolName`; the Wiki
  binding is typed on `WikiToolName` and instantiates `WikiToolCatalog` to decide which capabilities are
  writes. The latter is domain policy, not schema.
- The **read-only capability filter** (`capabilities_in`). Its default - an unset or unrecognised value
  reads as read-only - is a deliberate security decision about a specific wiki deployment.
- The **dialect factories** themselves, which construct Gmail and Atlassian clients returning
  `MailTools` and `WikiTools`.
- **Google's OAuth policy.** `mail/mcp/oauth.py` hard-codes Gmail scopes and reads `MAIL_MCP_OAUTH_*`
  settings. The generic parts - loopback callback, token storage, the `SecretStr` discipline - can move;
  the provider policy cannot. One control in particular must not be lost in transit:
  `PinnedScopeOAuthProvider` re-pins the requested scope before every authorisation attempt, because the
  SDK otherwise replaces it with whatever the resource server advertises - which for the official Gmail
  server includes full mailbox control, permanent deletion included. If that class is dropped or
  reimplemented casually during extraction, the agent silently acquires a key to the whole mailbox.

## Tier 3 - stays in this repository

### Framework adapters

`agents/maf/` and `agents/langgraph/` - chat client, reasoner, tool adapter, approval translator.

Tempting, since hosting agents is the library's mission. It should still be ruled out: **these adapters
are the object of the comparison study**. Moving them would make the library take sides and would tie
its release cadence to frameworks that move fast. The repository's `langchain>=1.3.3` floor - required
because the `when` predicate of the human-in-the-loop middleware only appeared in that release - is
exactly the coupling to avoid.

The `TextReasoner` protocol in `core/reasoning/ports.py` names no framework and could follow the fencing
work later, but its implementations stay with the adapters.

### The session loop

`mail/application/session.py` and `wiki/application/session.py` import `agent_framework` and LangGraph
respectively. The implementation must stay per framework.

The **policy** they apply, however, is shared and duplicated: bound the number of approval rounds, bound
the total number of rounds, and **explicitly decline whatever is still pending** rather than abandoning
a turn. Abandoning would let a later, unrelated turn replay answers given under a different premise.
Those bounds deserve a shared contract even though the code enforcing them stays here.

### Everything else

Capabilities, skills, domain models, in-memory datasets, MCP servers, composition roots, console
entrypoints and tool catalogues. That is the laboratory itself.

## Cross-cutting prerequisites

Independent of what moves, and to be handled first.

| Subject | State | Effect |
|---|---|---|
| `py.typed` | absent from the runtime's Python package | This repository carries a mypy waiver, `module = "ygo74.*"`, documented in `pyproject.toml`. Widening the boundary widens the blind spot. |
| Python version | runtime `>= 3.11`, this repository `>= 3.12` | `ConversationRuntimeCache` uses PEP 695 generic syntax. Rewrite with `TypeVar`, or raise the floor. |
| Optional extras | none in `packages/python/pyproject.toml` | `fastapi` is imported defensively in `fastapi_endpoints.py`. Hosting the MCP client or more HTTP code requires an extras policy (`http`, `mcp`). |
| Settings library | runtime depends on `pydantic`, `typing-extensions`, `PyJWT` only | Moving the HTTP settings adds `pydantic-settings` to every host. Decide whether the runtime imposes a settings library or accepts plain values. |
| Conversation header | defined on both sides | `x-conversation-id` appears in `core/serving/payloads.py` and in `domains/endpoints/header_forwarding.py`. Exactly one definition should be authoritative. |
| Observability | `observability/otel.py` returns a dictionary | It is a stub. This repository's audit trail and logging conventions are a possible contribution, not only an extraction. |
| Authentication context | handed over as a `dict` | As long as the entrypoint receives a dictionary, every application re-parses the context. Fixing the contract removes the need to extract `Principal` at all. |

## Proposed sequencing

Each step ships on its own and leaves the repository green. Dependencies are the real ones: a batch
listed here imports nothing that a later batch owns.

| # | Batch | Parity | Depends on | Status |
|---|---|---|---|---|
| 0 | `py.typed`, optional extras, decisions on Python 3.12 and on the settings library | - | - | **done** (extras and `py.typed` shipped; Python floor left at 3.11; settings library deferred with batch 11) |
| 1 | Immutable identity projection handed to the entrypoint | portable | 0 | **done** as `AgentPrincipal` |
| 2 | Conversation port, payload reading and rendering, unified header | portable | 1 | **done** |
| 3 | Capability registry contract (`SkillDescriptor`, `SkillRegistry`, manifests) | portable | 0 | **done** |
| 4 | Security posture primitives (operations, floor, permissions, context, audit) | portable | 0 | **done** |
| 5 | Tokens | portable | 1, 4 | deferred: `AccessToken` and the delegated-token ports stayed, pending the MCP batch that uses them |
| 6 | Descriptor factory, after deriving security schemes and tool invocation from configuration | portable | 2, 3 | pending |
| 7 | Human-approval domain, including the broker, the two ports and the storage contract | portable | 3, 4 | pending |
| 8 | Gated operation runner | portable | 4, 7 | pending |
| 9 | Untrusted content, fencing and `ReasoningRequest`, after opening `UntrustedOrigin` | portable | 4 | pending |
| 10 | `ConversationRuntimeCache`, after the lease and lock-scope repair | Python-first | 1, 2 | pending |
| 11 | Generic HTTP settings, with issuer discovery instead of the Keycloak path | portable | 0 | pending |
| 12 | MCP transport lifecycle, binding schema and registry mechanics | Python-first | 0 | pending |

### What the delivered batches actually cost

The sequencing above was written before any code moved, and three of its
assumptions were wrong.

- **Batch 3 could not ship alone.** `SkillManifest` carries a
  `ToolOperationDescriptor`, which carries a `Permission`, and
  `SkillDescriptor.invoke` takes a `UserContext`. The registry was inextricable
  from batch 4, so the two shipped together. Batches 1 and 2 did not have this
  problem, which is why they remain the right place to start.
- **`py.typed` was load-bearing, not cosmetic.** With the waiver in place, every
  type the library exposed was `Any`, and removing it turned up six real errors
  that strict type checking had been silently unable to see - including a call to
  a method that no longer existed.
- **Moving the error base broke every refusal boundary.** `SecurityError` used to
  derive from this repository's `DomainError`, so ten `except DomainError` sites
  quietly caught permission and confirmation refusals and rendered them to the
  model as "the operation did not happen". Once the base moved, those refusals
  escaped as unhandled exceptions instead. The fix - catching both hierarchies
  explicitly at each boundary - is the kind of thing a batch plan does not
  predict, and the reason the existing test suite was the precondition for the
  whole exercise.
- **The library's package root pulled a web framework into every import.**
  `ygo74/agent_runtime/__init__.py` re-exported eagerly, so importing the
  permission model executed it, which loaded the endpoint adapters, which imported
  FastAPI. The `http` extra was optional only in the sense that its absence did
  not crash. Adding the security model to that package root would have spread the
  problem to every domain layer here, so the root was made lazy upstream instead.
  The architecture test added in this repository now asserts the property
  end-to-end, in a subprocess, rather than by reading import statements - because
  reading import statements is exactly what failed to notice it.

Batches 1, 2, 6 and 10 empty `core/serving/` almost entirely and make `entrypoints/http.py` and
`entrypoints/service.py` nearly identical between the two agents, which is the drift described above.

Batches 7 and 8 are the most valuable and the most delicate: they are security properties, and moving
them without their test suites would amount to rewriting them.

### What has to be updated here at each batch

- `tests/architecture/test_distribution_boundaries.py` - the `DISTRIBUTIONS` mapping and the layer sets,
  which encode the boundaries checked mechanically;
- the `http` extras of `agents/mail/pyproject.toml` and `agents/wiki/pyproject.toml`, and the `http`
  extra of `agents/core/pyproject.toml`;
- `src` (ruff) and `mypy_path` / `packages` (mypy) in the root `pyproject.toml`;
- the `tests/security/` tests that follow a moved component.

## Recommendation

Start with the prerequisites, then batches 1 and 2. They are the least risky, they fix a real gap in the
library's contract, and they make the rest mechanical.

Treat batches 7 and 8 as one decision, taken explicitly. Together they are the contribution with the
most value for the library - a complete, deterministic human-approval path over a stateless API - and
they are the ones where a careless move would weaken a control rather than relocate it.

Repair `ConversationRuntimeCache` before publishing it, not after. Its defects are invisible at this
repository's settings and immediate at a library's.

Leave the framework adapters alone until the comparison study concludes.
