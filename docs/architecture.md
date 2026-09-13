# Architecture

## 1. Purpose

This repository is an enterprise AI agent laboratory. It evaluates agentic AI
frameworks (Microsoft Agent Framework, LangChain, CrewAI) against the same
business scenarios, the same domain logic and the same MCP tools.

The architecture exists to make that comparison fair: only the framework
adapter changes between two evaluations, never the business logic.

## 2. Layered architecture

```text
                         USER (CLI, later Teams / API)
                                     |
  ---------------------------------- v -------------------------------------
  frameworks/          Framework adapters          <-- ONLY layer aware of a
    microsoft_agent_framework/                         specific agent framework
    (later: langchain/, crewai/)
  ---------------------------------- | -------------------------------------
  agents/              Skill registry and capability bindings
                       (manifest + code, framework independent)
  ---------------------------------- | -------------------------------------
  skills/              Reusable domain capabilities
                       (orchestrate MCP tools + deterministic business logic)
  ---------------------------------- | -------------------------------------
  mcp/                 MCP contracts (Protocols, tool catalog, floors, errors)
  ---------------------------------- | -------------------------------------
  infrastructure/      Concrete implementations
                       mcp/       -> real MCP client       -> MCP server -> system
                       inmemory/  -> deterministic dataset -> tests / mock mode
                       config/    -> manifest and binding loaders
                       observability/
  ---------------------------------------------------------------------------
  domain/              Typed models, manifests, security primitives,
                       reasoning ports (no outgoing dependency at all)

  application/         Composition root, dependency injection, CLI
                       (builds the framework agent with its own public API)
```

Delivered configuration sits beside the code, not inside it:

```text
config/                Agent manifest, skill packages, MCP bindings
                       -> loaded by infrastructure/config
                       -> see docs/configuration.md
```

### Dependency rule

```text
domain  <-  mcp  <-  skills  <-  agents  <-  frameworks  <-  application
```

Dependencies point inwards only. This is enforced by
`tests/architecture/test_distribution_boundaries.py`, which fails the build when:

- `domain`, `mcp`, `skills` or `agents` import an agent framework;
- any layer other than `infrastructure` imports an enterprise system SDK
  (`google`, `googleapiclient`, `imaplib`, `smtplib`, `httpx`, ...);
- a lower layer imports a higher one.

## 3. Integration boundary

Agents never integrate with enterprise systems. The full chain is:

```text
User -> Agent -> Skill -> MCP Tool contract -> MCP Server -> Enterprise system
```

For the Mail Agent this means the agent, the skills and the domain contain no
Gmail, OAuth, IMAP, SMTP or Gmail API knowledge whatsoever. Those concerns live
inside the Mail MCP server, behind the `MailTools` contract.

## 4. Skills are the tools exposed to the LLM

A deliberate decision: the tools advertised to the model are the **skills**, not
the raw MCP tools.

```text
LLM  --selects-->  "search_mail" tool (framework adapter)
                          |
                          v
                   MailSearchSkill          deterministic business logic
                          |
                          v
                   MailTools (Protocol)     MCP contract
                          |
                          v
                   McpMailTools             MCP client -> MCP server -> Gmail
```

Consequences:

- the deterministic business logic can never be bypassed by the model;
- the same skills are re-exposed to another framework by writing one adapter;
- risk classification and confirmation are attached to a skill operation, not
  to a raw remote call.

## 5. Reasoning port

Skills that genuinely need an LLM (summarisation, classification, action
extraction, reply drafting) depend on the `TextReasoner` port defined in
`domain/reasoning`. Implementations:

- `MafTextReasoner` (frameworks/microsoft_agent_framework) for runtime;
- `ScriptedTextReasoner` (tests) for deterministic unit tests.

Skills therefore stay framework independent and testable without a network.

## 6. Security model

- every operation carries a `UserContext` (identity, never credentials);
- credentials live exclusively in the infrastructure / MCP server layer;
- all content returned by MCP is `UntrustedText` and is passed to the model
  inside an explicitly delimited, clearly labelled section;
- write operations are gated by a deterministic `ConfirmationPolicy`; the LLM
  can propose an action but never authorises it;
- confirmation decisions and executed writes are recorded in an audit trail.

## 7. Runtime modes

| Mode   | MailTools implementation | Requires network | Purpose                 |
|--------|--------------------------|------------------|-------------------------|
| `mock` | `InMemoryMailTools`      | no               | tests, demos, scenarios |
| `mcp`  | `McpMailTools`           | yes              | real Mail MCP server    |

The agent code and the skills are identical in both modes; only the composition
root wires a different implementation.

## 8. Repository layout

```text
agents/
  core/      src/ai_agent_lab/core/   security/  reasoning/  config/  observability/
  maf/       src/ai_agent_lab/maf/    Microsoft Agent Framework adapter
  mail/      src/ai_agent_lab/mail/   domain/  skills/  capabilities/  mcp/  application/
mcp-servers/
  protocol/  src/mail_mcp/protocol/   wire payloads, tool names, error codes
  gmail/     src/mail_mcp/gmail/      Gmail REST API server
  reference/ src/mail_mcp/reference/  dataset-backed server
tests/
  unit/  contract/  integration/  agent/  security/  architecture/
data/mail/         deterministic mailbox datasets
scenarios/mail/    reproducible agent scenarios
```

Two namespaces, and the boundary between them is the point: `mail_mcp` never
imports `ai_agent_lab`. A server we write and a server written elsewhere are
both reached through a dialect on the agent side, so neither is privileged. See
[repository-structure.md](./repository-structure.md).

Within each namespace the packages sit under a single root - `ai_agent_lab`,
`mail_mcp` - because publishing them as top-level modules would shadow
third-party distributions, in particular the `mcp` package used by the client.

## 9. Environments

One virtual environment per agent and per framework, so that framework
dependencies never leak into a comparison:

```text
.venvs/mail-agent-maf/     Mail Agent + Microsoft Agent Framework
```

`ai_agent_lab.core` is framework free; only `ai_agent_lab.maf` depends on an
agentic framework. Install everything in editable mode with
`python -m scripts.install`.

## 10. What this repository no longer owns

The security model, the authenticated caller, the conversation port and the
capability contracts moved to `ygo74-agent-runtime`. They contain no business
knowledge, and both agents had grown their own copy of the code around them - a
copy per agent being one copy away from a weaker security path.

| Concern | Now provided by |
|---|---|
| Permissions, user context, operation classification | `ygo74.agent_runtime.domains.security` |
| Security floor and audit trail | `ygo74.agent_runtime.domains.security` |
| Authenticated caller | `ygo74.agent_runtime.domains.auth.agent_principal` |
| Conversation port, manifests, capability registry | `ygo74.agent_runtime.domains.contracts` |
| Token ports (`AccessToken`, `TokenVerifier`, `DelegatedTokenSource`) | `ygo74.agent_runtime.domains.auth.tokens` |
| Manifest-derived discovery descriptor | `ygo74.agent_runtime.domains.discovery.manifest_descriptor` |
| Confirmation policy, tickets, approval parser, gated runner | `ygo74.agent_runtime.domains.humanapproval` |
| Untrusted content, prompt fence, reasoning request | `ygo74.agent_runtime.domains.security` |
| Conversation state cache | `ygo74.agent_runtime.domains.sessions` |
| OIDC discovery and generic HTTP settings | `ygo74.agent_runtime.domains.auth`, `.configuration` |
| Transport payload reading and reply rendering | `ygo74.agent_runtime.domains.endpoints` |

The library is therefore a **foundation** dependency of `ai_agent_lab.core`, not
an optional serving one. It is not a framework and not a transport: importing it
pulls in `pydantic` and `PyJWT`, and FastAPI stays behind its own extra. The
architecture tests pin that distinction - a domain, skill or capability may name
the library but must not reach `ygo74.agent_runtime.domains.endpoints`.

Two consequences worth knowing before an upgrade:

- the audit logger is named `ygo74.agent_runtime.audit`, not `ai_agent_lab.audit`;
- the refusal raised when a caller lacks a permission is `PermissionDeniedError`,
  because the library already had an `AuthorizationError` meaning something else.

And one behavioural change in discovery. The descriptor used to assert
`("jwt", "oidc")` and `toolInvocation: false` regardless of the deployment, which
was wrong on both counts for a service running on an API key and exposing fifteen
capabilities. Both are now derived: `AdvertisedSecurity.of(...)` reads the same
`jwt_validation`, `api_key_resolver` and `authenticators` the endpoints are
configured with, and tool invocation follows the declared skills. A descriptor
therefore reports what the service accepts, and a deployment that changes its
authentication cannot forget to update what it advertises.

That change had a consequence worth stating plainly: **the Mail Agent HTTP
service now refuses to start when nothing would identify a caller.** It
previously started and served the configured mailbox to anyone, because its JWT
wiring is commented out and it had no equivalent of the Wiki Agent's start-up
guard. Set `MAIL_AGENT_HTTP_API_KEY`, or re-enable `jwt_validation` in
`build_app`.

What is left of `ai_agent_lab.core` after all of this is small and deliberate:
`errors.py`, the configuration loaders, the `TextReasoner` port and its errors,
and the join between an identity and the permissions a deployment grants it. The
two `skills/gating.py` modules are one line each - a type alias binding this
agent's tool enumeration to the library's generic runner - because the permission
check, the confirmation policy and the audit record are the same three steps for
every agent and are written once.

Two changes worth knowing about when reading the agents:

- **Untrusted origins are declared per domain.** `MailOrigin.BODY` and
  `WikiOrigin.PAGE_TITLE` live in each agent's `domain/origins.py`, exactly as
  permissions do. The library used to carry a closed enumeration listing both
  agents' values, which meant a third agent could not be added without changing
  it.
- **A conversation is leased, not looked up.** `respond` holds
  `async with conversations.lease(...)`, so eviction and expiry cannot close the
  MCP session a turn is still using. The previous `acquire` is gone rather than
  deprecated, so a missed call site is an import error.

The MCP plumbing - transport lifecycle, binding schema, dialect registry and the
generic OAuth pieces - is available in `ygo74.agent_runtime.domains.mcp` but the
two agents still carry their own copies. Rebinding them is the last step of the
extraction and has not been taken yet.

What stays here, and why, is recorded in
[runtime-extraction-candidates.md](./runtime-extraction-candidates.md).
