# Agent Design

This page covers agent and framework composition. The repository-wide
responsibilities and runtime boundary are defined in
[the system specification](../README.md).

## 1. What an agent is in this repository

An agent is built with the API of its framework, directly. There is no house
abstraction over an agent: a developer reads `Agent(...)` in the composition root
and finds the public documentation of that call, rather than a wrapper this
repository would have to document, support and teach.

What the repository does own is what makes an agent's capabilities reusable
across frameworks:

- an **agent manifest** and a separate `AGENT.md` file for agent identity and
  instructions;
- a **skill manifest** and a separate `SKILL.md` file for each capability's
  description, operation security posture, and instructions;
- a **skill registry**, built in code: the capabilities bound to the coroutines
  that run them;
- an **adapter**, per framework: registry entries turned into that framework's
  tools.

An agent contains no business logic, no integration code and no reasoning
implementation. Business logic belongs to skills; integrations belong to MCP
servers. The shared manifest loaders and `TextReasoner` port are public Python
APIs from `ai-enterprise-agent-runtime`.

The YAML shapes are fixed contracts published as Draft 2020-12 schemas by the
runtime. The schemas validate `agent.yaml` and `skill.yaml`; `AGENT.md` and
`SKILL.md` remain separate Markdown inputs and are not schema-validated.

## 2. Skill registry

```text
SkillRegistry
  skills: Sequence[SkillDescriptor]

SkillDescriptor
  tool_name: str            name advertised to the model
  description: str          description used by the model to select the tool
  input_model: type[BaseModel]
  operation: ToolOperationDescriptor   READ/WRITE + risk + confirmation
  invoke: Callable[[BaseModel, UserContext], Awaitable[SkillResult]]
```

`tool_name`, `description` and `operation` come from the delivered manifest;
`input_model` and `invoke` come from the code. `SkillDescriptor.from_manifest`
is where the two meet.

The descriptor is the shared contract used by framework adapters. The Mail
agent maps it to Microsoft Agent Framework tools; the Wiki agent builds its
LangChain graph with the framework's public APIs. Framework integration does
not duplicate skill behavior or impose a repository-owned agent abstraction.

## 3. Framework adapter responsibilities

A framework adapter translates between repository contracts and framework
conventions. The current adapters have different responsibilities:

| Responsibility | Mail / Microsoft Agent Framework | Wiki / LangChain and LangGraph |
|---|---|---|
| Build the agent | `agent_framework.Agent` and `FunctionTool` | `create_agent` and Wiki's graph composition |
| Suspend a protected tool | `approval_mode="always_require"` and `AgentSession` | `HumanInTheLoopMiddleware` and graph interrupts |
| Resume a pending action | Agent Framework approval response content | LangGraph `Command` through the runtime binding |
| HTTP conversation hosting | Runtime conversation engine with the Mail session | Runtime managed worker with the Wiki conversation factory |
| Neutral result and stream conversion | Runtime Agent Framework integration | Runtime LangChain integration |

Application adapters supply the domain-specific skill, resolver, and policy
behavior. The runtime LangChain integration owns native invocation and output
conversion, while the Wiki composition root owns the graph and tool admission.
The framework-neutral `TextReasoner` port is
`ygo74.agent_runtime.domains.reasoning.ports.TextReasoner`; framework
implementations stay in this repository's adapters.

See [LangChain and LangGraph in the Wiki agent](../integrations/langchain-langgraph.md)
for the Wiki flow and ownership boundary.

> API note: this repository targets the GA API of Microsoft Agent Framework
> (`Agent`, `AgentResponse`, `Message`, `Content`, `@tool`, `AgentSession`).
> Pre-GA examples using `ChatAgent`, `AgentRunResponse`, `ChatMessage`,
> `TextContent` or `@ai_function` do not apply.

## 4. The Mail Agent

```text
Mail agent manifest + skill registry
    |
    +-- MailSearchSkill              READ
    +-- MailReadSkill                READ   (message / thread retrieval)
    +-- MailSummarySkill             READ
    +-- MailClassificationSkill      READ
    +-- MailActionExtractionSkill    READ
    +-- MailReplySkill               READ*  (drafts only, never sends)
    +-- SendMailSkill                WRITE  confirmation required
    +-- MailManagementSkill          WRITE  confirmation required
                 |
                 v
            MailTools (MCP contract)
                 |
                 v
            Mail MCP Server -> Gmail
```

`MailReplySkill` produces a `MailDraft` and returns it. It never sends.
Sending is a separate, explicitly gated capability.

## 5. Confirmation model

Confirmation is decided by deterministic code, never by the model.

```text
ToolOperationDescriptor (READ|WRITE, risk level)
            |
            v
ConfirmationPolicy.requires_confirmation(operation, user)   <-- configurable
            |
    +-------+--------+
    | no             | yes
    v                v
execute        emit ConfirmationRequest
                     |
                     v
               user answers (CLI / UI)
                     |
            +--------+--------+
            | approved        | rejected
            v                 v
        execute + audit   abort + audit
```

Two independent guards enforce this:

1. the framework adapter registers gated tools with `approval_mode`
   `always_require`, so the framework suspends the call;
2. write skills re-check the policy themselves and raise
   `ConfirmationRequiredError` if no valid decision is attached.

Guard 2 means the rule holds even if a skill is invoked outside any framework.

The request shown to the user, the request that authorises the call and the
request recorded in the audit trail are one and the same object, carried across
by a `ConfirmationLedger`. Entries are consumed once and scoped to their owner,
and `ConfirmationGate` verifies that the request was issued for the caller and
answered by them.

### Configurability

The policy is data driven and resolved per user:

- a built-in default classification per tool;
- repository-level overrides from configuration (`.env`);
- per-user overrides supplied by a `ConfirmationPreferenceStore`.

`mark_read` is classified WRITE / confirmation required by default and can be
auto-approved through configuration.

## 6. Observability

Every agent run and every skill execution emits a structured record:

```text
trace_id, agent, skill, tool, operation_type, user_id,
duration_ms, status, error_type
```

Never logged: credentials, tokens, email bodies, recipient lists, subjects.
Messages are referenced by identifier only.

## 7. Output contract

Skills return structured results that separate:

- facts (grounded in retrieved messages, with source identifiers);
- analysis and inference (explicitly marked as inferred);
- recommended actions;
- uncertainties.

Inferred information is never presented as fact.

## 8. Prompt injection posture

Retrieved mail content is untrusted data, not instruction. Every reasoning call
is built by `PromptEnvelopeBuilder`, which:

- places trusted instructions and the user request outside the data section;
- wraps every piece of retrieved content in a delimited, labelled block;
- states that content inside the block must be treated as data only.

The structural guarantee is stronger than the prompt: no mail content can reach
a write operation without passing the deterministic confirmation policy.
