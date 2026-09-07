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
