# AI Agent Lab — System Specification

This document is the system-level specification for the Python applications in
this repository. It describes the current system boundary, component ownership,
runtime flow, configuration contracts, and security behavior. Framework- and
agent-specific detail lives in the architecture and integration specifications
under this directory.

## Purpose and scope

AI Agent Lab develops and compares enterprise agents while keeping their
functional capabilities, security decisions, scenarios, and MCP contracts
independent of the agent framework. The Mail agent uses Microsoft Agent
Framework; the Wiki agent uses LangChain/LangGraph. A new framework integration
is an adapter and composition change, not a second implementation of the
agent's business behavior.

This repository contains the Mail and Wiki applications, their MCP clients and
server distributions, delivered configuration, datasets, and tests. It does not
own the shared technical agent runtime. Common configuration loading, manifest
schemas, runtime contracts, security primitives, user-context construction,
common errors, and the framework-neutral reasoning port are provided by
[`ai-enterprise-agent-runtime`](https://github.com/ygo74/ai-enterprise-agent-runtime).
The runtime's system-level specification is its
[`spec/README.md`](https://github.com/ygo74/ai-enterprise-agent-runtime/blob/main/spec/README.md).

## System context and flow

```mermaid
flowchart LR
    User[User or calling service] --> Host[Agent composition root]
    Config[Delivered agent and skill files] --> Loader[Runtime configuration loaders]
    Loader --> Registry[Code skill registry]
    Registry --> Adapter[Framework adapter]
    Host --> Adapter
    Adapter --> Skills[Agent skills]
    Skills --> Client[MCP client and dialect]
    Client --> Server[MCP server]
    Server --> System[Enterprise system]
    Skills --> Reasoner[Runtime TextReasoner port]
    Reasoner --> Model[Configured model provider]
```

The application composition root loads delivered configuration, constructs the
runtime user context from the authenticated principal and application-supplied
permissions, binds manifests to implemented skills, and builds an agent using
the selected framework's public API. The framework adapter translates calls to
and from skill descriptors; it does not own domain rules. Skills orchestrate
deterministic business logic and MCP tool contracts. The runtime supplies the
generic HTTP conversation container and turn engine, bounded approval-loop
orchestration, and MCP binding, connection, and dialect-registry mechanics.
Each application composes those APIs with its own tools, policies, and framework
session adapter. The concrete agent-side dialect translates between the
application's tool contract and the selected MCP server.

Agents do not integrate with enterprise systems directly. A system is reached
through an MCP server, whether that server is maintained here or supplied by a
third party. The agent-side dialect is the compatibility boundary.

## HTTP conversation lifecycle

Mail and Wiki use the runtime's generic conversation flow while keeping their
framework runtimes distinct. `MailConversation` and `WikiConversation` are
typed specializations of `AgentConversation` for their respective application
runtime and session types; neither application runtime inherits from a shared
Mail/Wiki base class. Each local conversation factory composes the runtime,
framework session adapter, pending-confirmation store, confirmed-operation
runner, and renderer for its domain.

An HTTP turn follows this sequence:

1. The agent entrypoint converts the authenticated request payload into a
   `ConversationTurn` containing the caller, conversation ID, and user message.
   The caller comes from the endpoint authentication context, not from a body
   field. Mail additionally requires an email address to select a mailbox.
2. `HttpConversationEngine` leases the conversation from
   `ConversationRuntimeCache`, partitioned by authenticated caller and
   conversation ID. The lease keeps an active turn's resources open; expiry or
   eviction closes idle conversations, and service shutdown closes the cache.
3. The engine recognizes exact confirmation commands before calling the agent.
   It asks the application runner to claim and execute the saved operation
   within its user and conversation scope. An ordinary message instead goes to
   the framework session's `ask` method.
4. The Mail and Wiki session adapters use the runtime's bounded `ApprovalLoop`
   to process framework-suspended tool calls. It centralizes approval-question
   and total-turn limits and clears recorded grants before bounded decline
   cleanup. The adapters retain framework-specific state handling: Mail
   resumes a Microsoft Agent Framework `AgentSession`; Wiki resumes LangGraph
   state through its thread ID and resume command. Pending-confirmation policy
   and the person-facing approval resolver remain application-owned.
5. The engine returns an `AgentReply` with the answer, rendered pending-action
   details, and pending ticket identifiers. The HTTP entrypoint maps that
   result back to the configured provider response shape.

This division keeps caller scoping, ticket handling, turn cleanup, and reply
assembly consistent while allowing each application to choose its framework,
agent runtime, confirmation policy, and presentation. The generic conversation
and approval APIs are Python-first; they do not make the framework sessions or
the Mail and Wiki composition roots interchangeable.

## Components and ownership

| Component | Responsibility | Owner |
|---|---|---|
| `ai_agent_lab.mail`, `ai_agent_lab.wiki` | Agent-specific models, skills, capability policies, tool ports, composition roots, and conversation factories | This repository |
| `ai_agent_lab.maf`, `ai_agent_lab.langgraph` | Framework adapters and framework-specific session-state handling | This repository |
| `ai_agent_lab.core` | Shared chat-provider choices and Azure credential provider only | This repository |
| `mail_mcp.*`, `wiki_mcp.*` | Concrete MCP tool contracts and dialect adapters, plus MCP server implementations | This repository |
| Runtime configuration, contracts, errors, reasoning, identity, security, generic conversation and approval APIs, and MCP client mechanics | Reusable technical foundations | `ai-enterprise-agent-runtime` |
| Prompts and agent/skill YAML, Markdown, and MCP bindings | Deployment-delivered behavior and integration selection | `config/` in this repository |

The application owns which permissions a principal receives. The runtime's
`UserContextFactory` copies that identity and those permissions into an immutable
context; it does not infer a role policy. `azure_credentials.py` and `chat.py`
remain in core because they describe the current agents' model configuration.
Mail and Wiki retain their runtime composition roots and factories, concrete
MAF/LangGraph session adapters, capability catalogs and filters, credential and
secret handling, and domain-specific dialect behavior. They pass application
capability enums, resolved transport settings, and any caller-specific HTTP
headers to the generic runtime APIs; the runtime does not own those policies or
secrets. These newly adopted conversation and MCP APIs are Python-first and do
not imply .NET or Java parity.

## Configuration contracts

Python agents use `YGO74_AGENT_RUNTIME_CONFIG_DIR` to select the configuration
directory. If it is unset, the runtime's configuration discovery rules apply.
Mail and Wiki declare the runtime `configuration` extra, which provides
configuration discovery, `.env` loading, safe YAML parsing, and manifest
validation without requiring the runtime HTTP extra.

The YAML structures are fixed versioned contracts. Draft 2020-12 schemas are
published as runtime package resources:

- `agent.yaml`: `urn:ygo74:agent-runtime:agent-manifest:1`
- `skill.yaml`: `urn:ygo74:agent-runtime:skill-manifest:1`

The schemas reject unknown fields and validate structural values and enums.
`AGENT.md` and `SKILL.md` are separate Markdown inputs and are not covered by
those schemas. The application still resolves permissions against its registry
and the runtime still enforces the configured security floor; a valid schema
does not grant permission to perform an operation.

Changes to the accepted YAML structure are versioned public-contract changes.
The typed input models, packaged schemas, schema identifiers, and documentation
must be updated together.

## Security behavior

- Credentials remain in infrastructure and credential providers. They are not
  stored in `UserContext`, included in prompts, or logged.
- A `UserContext` identifies the caller and carries application-supplied
  permissions; it is not an authentication credential or a source of policy.
- All free text returned by an MCP tool is untrusted. Reasoning prompts fence it
  as data, separate from trusted instructions.
- A model can propose a write but cannot authorize it. Deterministic operation
  classification, permission checks, and confirmation gates control writes.
- Confirmation requests are scoped to the user, consumed once, and audited with
  identifiers rather than message or document contents.
- MCP servers remain separate from agent domain packages and do not import
  `ai_agent_lab`.

## Runtime and deployment modes

The `mock` composition uses deterministic in-memory tools and needs no service
network. The `mcp` composition reaches configured MCP servers. Tests and
scenarios use deterministic fakes and do not require real model credentials.
Each agent/framework distribution is installed into its own environment so its
framework dependencies do not contaminate the comparison. HTTP entrypoints
require an explicit caller-authentication mechanism unless anonymous service is
deliberately selected.

## Architectural constraints

The architecture test suite enforces declared distribution dependencies,
framework isolation, allowed runtime-domain imports, layer direction, and the
absence of imports from MCP server namespaces into `ai_agent_lab`. The shared
runtime is consumed through its public Python module paths; this repository does
not maintain duplicate implementations or compatibility aliases for migrated
runtime APIs.

## Detailed specifications

- [Architecture and dependency boundaries](architecture/architecture.md)
- [Agent and framework design](architecture/agent-design.md)
- [Mail HTTP and conversation integration](../docs/mail-agent-http.md)
- [Wiki HTTP and conversation integration](../docs/wiki-agent-http.md)
- [Configuration and manifest contracts](../docs/configuration.md)
- [MCP tool and server boundaries](integrations/mcp-design.md)
- [Repository distributions and installation](architecture/repository-structure.md)
- [Runtime extraction decisions](architecture/runtime-extraction-candidates.md)
- [Adding a new agent](../docs/implementing-an-agent.md)

## Task records

The design and implementation plans for issues #5 and #6 are preserved as task
records. The current system specification above describes the resulting
system.

- [Issue #5 specification](tasks/issue-5/SPEC.md)
- [Issue #5 implementation plan](tasks/issue-5/PLAN.md)
- [Issue #6 specification](../docs/tasks/issue-6/SPEC.md)
- [Issue #6 implementation plan](../docs/tasks/issue-6/PLAN.md)
