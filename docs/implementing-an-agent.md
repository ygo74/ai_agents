# Implementing a new agent

This is the order in which an agent is actually built here, and the reason each
step comes where it does. The Mail Agent and the Wiki Agent are the worked
examples: everything below points at real files in one or both of them.

Two agents exist, on two different frameworks, and they share almost all of their
structure. That is not a coincidence — it is the result of putting the
cross-cutting concerns in [`ygo74-agent-runtime`](https://pypi.org/project/ygo74-agent-runtime/)
and keeping the framework at the very edge. A third agent should feel like
filling in a shape that already exists.

## What you write, and what you get

| Concern | Where it lives |
|---|---|
| Permissions, operation catalogue, security floor, untrusted origins | **You write it** — it is your domain |
| Tool contracts, domain models, capabilities, skills | **You write it** — it is your domain |
| Confirmation policy, tickets, ledger, gated execution | The library |
| Authentication, JWT validation, API keys, role policies | The library |
| OpenAI / Anthropic / discovery endpoints, payload shapes | The library |
| Conversation cache, prompt envelope, untrusted fencing | The library |
| MCP binding, transport, dialects, OAuth | The library |

The rule behind that table: **anything that would be the same for any agent
belongs in the library; anything that encodes what your domain means belongs in
your agent.** When you find yourself about to write a second copy of something,
that is the signal it was a library concern.

---

## Step 0 — Decide what the agent is *not* allowed to do

Before any code. Write down the operations the agent will offer and, for each:
does it read or change the outside world, how much damage can it do, and who
should be allowed to ask for it.

This is first because every later step depends on it and because it is the one
answer a language model must never be able to influence.

Look at [`wiki/security_floor.py`](../agents/wiki/src/ai_agent_lab/wiki/security_floor.py)
to see what the output of this thinking looks like: `update_page` and
`delete_page` may never be presented as milder than they are, whatever a
delivered configuration says — while `create_page` and `add_comment` are
deliberately *not* floored, because they add without removing.

---

## Step 1 — Declare the permissions

```python
# agents/<name>/src/ai_agent_lab/<name>/domain/permissions.py
from typing import Final
from ygo74.agent_runtime.domains.security.permissions import Permission

class WikiPermission:
    READ: Final = Permission("wiki", "read")
    WRITE: Final = Permission("wiki", "write")
    ...
```

A permission is namespaced by domain, so the mail permissions and the wiki
permissions cannot collide and neither domain has to know the other exists.

Register them in a `PermissionRegistry` at the composition root. An operation
that requires an unregistered permission then fails at start-up rather than at
the moment somebody tries to use it.

**Worked examples:** [`wiki/domain/permissions.py`](../agents/wiki/src/ai_agent_lab/wiki/domain/permissions.py),
[`mail/domain/permissions.py`](../agents/mail/src/ai_agent_lab/mail/domain/permissions.py).

---

## Step 2 — Declare the untrusted origins

Everything that comes back from a wiki, a mailbox or the web is *data*, never
instruction. The library gives you `UntrustedOrigin`, `UntrustedText` and
`UntrustedFence`; you declare what sorts of content your domain produces.

```python
# domain/origins.py
class WikiOrigin:
    PAGE_TITLE: Final = UntrustedOrigin("wiki", "page_title")
    PAGE_BODY: Final = UntrustedOrigin("wiki", "page_body")
    ...
```

An origin names a *kind* of content, never its contents, so it is safe to log —
which is what makes it useful when a prompt injection attempt has to be traced
after the fact.

**Worked example:** [`wiki/domain/origins.py`](../agents/wiki/src/ai_agent_lab/wiki/domain/origins.py).

---

## Step 3 — Write the operation catalogue

One `ToolOperationDescriptor` per tool, declaring as *data* what it does:

```python
ToolOperationDescriptor(
    tool_name="delete_page",
    operation_type=OperationType.WRITE,
    risk_level=RiskLevel.HIGH,
    required_permission=WikiPermission.DELETE,
    confirmation_required_by_default=True,
)
```

Two things to get right here.

**Descriptions are a correctness concern, not documentation.** The model picks a
tool by reading them. On a wiki, the difference between "find the page" and "read
the page" is the difference between a cheap call and one that fills a context
window, and only the description tells the model which is which.

**The catalogue is the default; the floor is the limit.** A delivered skill
package may raise a risk level or demand a confirmation the catalogue did not,
but the `SecurityFloor` from step 0 is what it may never go below. Both the
confirmation gate and the audit trail read the same catalogue, which is what
keeps them from disagreeing.

**Worked examples:** [`wiki/catalog.py`](../agents/wiki/src/ai_agent_lab/wiki/catalog.py),
[`mail/catalog.py`](../agents/mail/src/ai_agent_lab/mail/catalog.py).

---

## Step 4 — Define the tool port

A `Protocol` per cohesive group of operations, written in **domain types only**.
No HTTP, no MCP, no vendor.

```python
@runtime_checkable
class WikiReadTools(Protocol):
    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult: ...
    async def get_page(self, page_id: str, user: UserContext) -> WikiPage: ...
```

Every method takes a `UserContext`. That is not ceremony: a wiki restricts pages
per person, and a call without an identity returns what a service account can see
rather than what the user can — which is a data leak that looks like a feature.

Split the port into focused protocols so a skill depends only on what it uses,
then compose them for implementations. The lab runs against Confluence Cloud and
the target is Data Center; they differ in authentication, REST version and half
their endpoints, and none of that reaches above this line.

**Worked examples:** [`wiki/tools_port.py`](../agents/wiki/src/ai_agent_lab/wiki/tools_port.py),
[`mail/tools_port.py`](../agents/mail/src/ai_agent_lab/mail/tools_port.py).

---

## Step 5 — Implement the port twice

**An in-memory implementation first.** It is not a stub for later — it is what
makes the suite deterministic, and what `<AGENT>_MODE=mock` runs. Write it before
the real one and the design stays honest, because nothing about the vendor can
leak upward into an interface the fixture also has to satisfy.

**Then the MCP implementation.** This is the only place that knows a protocol
exists. The library provides `McpConnection`, `McpServerBinding`,
`McpServerBindingLoader`, `DialectRegistry` and `PinnedScopeOAuthProvider`, so
what you write is the mapping between your domain models and the tool payloads —
not the transport.

An agent **never** calls Confluence, Gmail, a database or an enterprise API
directly. It calls tools exposed by an MCP server. That boundary is what lets the
credential live in a different container from the agent, which is the whole shape
of [deployment.md](deployment.md).

**Worked examples:** [`wiki/inmemory/`](../agents/wiki/src/ai_agent_lab/wiki/inmemory),
[`wiki/mcp/`](../agents/wiki/src/ai_agent_lab/wiki/mcp).

---

## Step 6 — Write the capabilities

A capability is one invocable unit: it validates its input, calls the tool port,
and renders a result. It is the layer where an `UntrustedText` is fenced before
it can reach the model.

Keep deterministic work deterministic. Filtering, sorting, date arithmetic and
rule-based decisions belong in code. Ask the model only for what it is genuinely
better at — which is reading and writing prose.

**Worked examples:** [`wiki/capabilities/`](../agents/wiki/src/ai_agent_lab/wiki/capabilities),
[`mail/capabilities/`](../agents/mail/src/ai_agent_lab/mail/capabilities).

---

## Step 7 — Write the skills

A skill is a reusable domain capability: `WikiAnswerSkill`, `MailThreadAnalysis`,
`WikiFreshnessSkill`. It may orchestrate several capabilities. It receives its
collaborators through the constructor and never constructs infrastructure.

Skills are **framework-independent by construction**. The same skill is used by
the LangGraph agent and by the Microsoft Agent Framework agent; if you find
yourself writing a LangChain-flavoured skill, the framework has leaked a layer too
deep.

Register them as `SkillDescriptor` in a `SkillRegistry`. The registry is what the
framework adapter turns into tools, and what discovery turns into the advertised
capability list.

**Worked examples:** [`wiki/skills/`](../agents/wiki/src/ai_agent_lab/wiki/skills),
[`mail/skills/`](../agents/mail/src/ai_agent_lab/mail/skills).

---

## Step 8 — Build the composition root

The **only** place allowed to instantiate concrete implementations. Everything
else receives its collaborators, which is what makes the skills testable, the
mock mode a configuration choice and the framework replaceable.

It wires: settings → tool port implementation → capabilities → skills → registry
→ permission registry → operation catalogue → confirmation gate → audit trail →
prompt envelope → the framework's agent object.

Two traps worth naming, both found the hard way:

- **Do not use a caller-supplied conversation identifier as a framework state
  key.** LangGraph keys persisted state by `thread_id`; using the caller's string
  directly lets somebody resume another person's conversation by guessing it.
  Derive it from the authenticated subject *and* the conversation, so the half the
  caller controls is only half. See
  [`wiki/application/composition.py`](../agents/wiki/src/ai_agent_lab/wiki/application/composition.py).
- **Build the agent with the framework's own API.** There is no house wrapper to
  learn: a developer reads `create_agent(...)` and finds the public
  documentation of that call. What this repository owns is what makes skills
  reusable — the manifests, the registry, the adapter, the confirmation policy —
  not a layer over the framework.

---

## Step 9 — Handle confirmations

Anything that changes the outside world does not happen in the turn that proposes
it. The agent answers with a ticket; the user replies `CONFIRM cfm-…` or
`CANCEL cfm-…`; the stored operation is then performed exactly as stored.

The library provides the whole mechanism — `ConfirmationGate`,
`ConfirmationBroker`, `ConfirmationLedger`, `ConfirmationCommandParser`,
`ConfirmedOperationRunner`, `GatedOperationRunner`, `PendingConfirmationRenderer`.
What you write is the **presenter**: how a pending operation is described to a
human.

Describe it in the user's terms, not the system's. A ticket that says only
`apply_label(m-alpha-1, FINANCE)` asks somebody to approve an identifier. Name the
message, the subject and the sender, because the answer may come several turns
later and nobody should have to scroll back to find out what they are approving.

And the reason for all of it: **a model must never be the authority on whether a
side effect happens.** A chat API has no side channel to hold a turn open on, so
the ticket is not a limitation of the transport — it is the design.

**Worked example:** [`wiki/application/confirmation_presenter.py`](../agents/wiki/src/ai_agent_lab/wiki/application/confirmation_presenter.py).

---

## Step 10 — Expose it over HTTP

The routes, the OpenAI payload shapes, the JWT validation and discovery all come
from the library. You write a `build_app()` that assembles them:

```python
add_ai_endpoints(
    app,
    WikiAgentEntrypoint(WikiConversationEngine(conversations)),
    default_route_key=AGENT_ID,
    enable_openai_chat_completions=True,
    jwt_validation=jwt_validation,
    require_bearer_token=True,
    api_key_resolver=api_key_resolver,
    descriptor_registry=DescriptorRegistry([descriptor]),
    discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
)
```

Three decisions to copy rather than reinvent:

- **Refuse to start with no way to identify a caller.** Neither an issuer nor an
  API key configured means the service cannot tell callers apart — so it stops,
  loudly, instead of serving one person's data to whoever asks first. Both agents
  raise a `…ServiceConfigurationError` for exactly this.
- **The two credentials are mutually exclusive.** An issuer wins and the API key
  is ignored. A static key left next to a configured realm is the kind of
  leftover that outlives the demonstration it was added for.
- **Discovery is authenticated.** Listing the agent lists every capability
  description, which is a map of what the system can be made to do.

Derive the advertised security from the *real* configuration with
`AdvertisedSecurity.of(...)` rather than writing it out by hand, so discovery
cannot advertise a scheme the service does not accept.

**Worked examples:** [`wiki/application/entrypoints/service.py`](../agents/wiki/src/ai_agent_lab/wiki/application/entrypoints/service.py),
[`mail/application/entrypoints/service.py`](../agents/mail/src/ai_agent_lab/mail/application/entrypoints/service.py),
and [mail-agent-http.md](mail-agent-http.md) / [wiki-agent-http.md](wiki-agent-http.md).

---

## Step 11 — Tests

Nothing here is optional, and the suite runs with no network and no credential.

| Kind | What it proves |
|---|---|
| Unit | Skills and capabilities against fakes injected through the constructor |
| Integration | Agent → skill → MCP client → a controlled server |
| Scenario | A reproducible turn: input, tools available, expected tool use, expected result |
| Security | Unauthorised access, cross-user access, prompt injection, tool misuse, confirmation bypass, data leakage |

The security tests are the ones that matter most and are most often forgotten.
A gate that is documented but not tested is a gate that will be removed by a
refactor six months from now and nobody will notice. Both existing agents have a
test that fails if the authentication guard disappears — write yours before you
need it.

---

## Step 12 — Package it

1. Add the distribution to `scripts/install.py`: its path, its extras, and the
   environments it belongs to. Keep the two agentic frameworks apart — one agent,
   one framework, which is what keeps the comparison meaningful.
2. Add it to `pyproject.toml`: `[tool.ruff] src`, `[tool.mypy] mypy_path` and
   `packages`. Strict typing is not negotiable at the security boundary.
3. Write `deploy/<name>-agent.Dockerfile`, copying one of the two existing ones.
   Two stages, `python:3.12-slim`, non-root, `config/` bundled and overridable
   through `AI_AGENT_LAB_CONFIG_DIR`, and a health check.
4. Add it to the matrix in
   [`.github/workflows/images.yml`](../.github/workflows/images.yml). Three lines:
   the name and the Dockerfile.
5. Document it in [deployment.md](deployment.md): its port, what it needs, and
   who may reach it.

---

## The mistakes that cost the most time

- **Reaching an enterprise system from a skill.** It always works on the first
  day, and it makes the credential impossible to isolate afterwards. Go through
  MCP even when MCP feels like overhead.
- **Asking the model to do arithmetic, filtering or sorting.** It will be right
  most of the time, which is the worst possible failure mode. Write it in code.
- **Treating retrieved content as instruction.** An email body and a wiki page
  are attacker-controlled in any deployment worth defending. Fence them.
- **Letting the framework leak below the composition root.** The moment a skill
  imports LangChain, the agent stops being comparable with the other one and the
  skill stops being reusable.
- **Trusting a `UserContext` the caller supplied.** It comes from the
  authenticated subject, never from a request field.

---

## Related

- [architecture.md](architecture.md) — the layers and why they are where they are
- [agent-design.md](agent-design.md) — what an agent is responsible for
- [mcp-design.md](mcp-design.md) — the integration boundary
- [configuration.md](configuration.md) — every setting and where it is read
- [repository-structure.md](repository-structure.md) — the ten distributions
- [deployment.md](deployment.md) — running it as a container
