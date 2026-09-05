# Agent Design

## 1. What an agent is in this repository

An agent is a thin, framework-independent definition:

- an identity (name, description);
- system instructions;
- a set of skill descriptors it is allowed to expose;
- nothing else.

An agent contains no business logic, no integration code and no reasoning
implementation. Business logic belongs to skills; integrations belong to MCP
servers.

## 2. Framework-independent agent definition

```text
AgentDefinition
  name: str
  description: str
  instructions: str
  skills: Sequence[SkillDescriptor]

SkillDescriptor
  tool_name: str            name advertised to the model
  description: str          description used by the model to select the tool
  input_model: type[BaseModel]
  operation: ToolOperationDescriptor   READ/WRITE + risk + confirmation
  invoke: Callable[[BaseModel, UserContext], Awaitable[SkillResult]]
```

The descriptor is the single contract a framework adapter needs. Adding
LangChain or CrewAI support means writing one adapter that reads descriptors -
no business code is duplicated.

## 3. Framework adapter responsibilities

A framework adapter translates between repository abstractions and framework
conventions. For Microsoft Agent Framework 1.17:

| Repository concept          | Microsoft Agent Framework 1.17            |
|-----------------------------|-------------------------------------------|
| `AgentDefinition`           | `agent_framework.Agent`                   |
| `SkillDescriptor`           | `agent_framework.FunctionTool` (`@tool`)  |
| confirmation required       | `approval_mode="always_require"`          |
| confirmation orchestration  | `ToolApprovalMiddleware` + `AgentSession` |
| pending confirmation        | `AgentResponse.user_input_requests`       |
| confirmation answer         | `Content.from_function_approval_response` |
| `TextReasoner`              | a chat client `get_response` call         |

The adapter must not contain domain rules. It maps types and wires middleware.

> API note: this repository targets the GA API of Microsoft Agent Framework
> (`Agent`, `AgentResponse`, `Message`, `Content`, `@tool`, `AgentSession`).
> Pre-GA examples using `ChatAgent`, `AgentRunResponse`, `ChatMessage`,
> `TextContent` or `@ai_function` do not apply.

## 4. The Mail Agent

```text
MailAgentDefinition
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
