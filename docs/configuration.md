# Configuration

Instructions, tool descriptions, prompts, approval defaults and MCP tool names
are delivered as configuration, separately from the code. Changing how the agent
speaks, what it is allowed to do or which MCP server it talks to is a delivery of
`config/`, not a release of the package.

## Where it lives

`config/` at the repository root, or wherever `AI_AGENT_LAB_CONFIG_DIR` points.

```text
config/
  agents/mail/
    agent.yaml          identity and the capabilities offered, in order
    AGENT.md            system instructions
  skills/mail/<tool>/
    skill.yaml          identity, security posture, MCP tools allowed
    SKILL.md            reasoning instructions (capabilities driven by a model)
  mcp/mail.yaml         logical tool name -> deployed MCP server tool name
```

## What is configuration, and what is not

| Delivered as configuration | Stays in code |
|---|---|
| System instructions, tool descriptions, prompts | Deterministic logic: filtering, recipients, draft references |
| Risk level, permission, confirmation default | The floor those values may not go below |
| Which capabilities the agent exposes | Argument schemas, which are typed contracts |
| Which MCP tool each capability may use | Grounding checks and the audit trail |

The dividing line is not taste. Filtering a mailbox, deciding who a reply goes to
and gating a state-changing call are rules with a right answer; expressing them
as prose for a model to follow would trade correctness for flexibility nobody
asked for. Conversely, how a summary is worded is exactly the kind of thing that
should change without a release.

## A skill package

```yaml
# config/skills/mail/summarise_mail/skill.yaml
tool_name: summarise_mail
implementation: mail.summarise      # binds the manifest to the code that runs it
description: >-
  Summarise a message or a whole conversation. ...
operation:
  type: READ                        # READ | WRITE
  risk: LOW                         # LOW | MEDIUM | HIGH
  permission: mail:read
  confirmation_required: false
mcp_tools:
  - get_mail
  - get_thread
```

`SKILL.md` next to it carries the reasoning instructions. A deterministic
capability has no `SKILL.md`: it has nothing to say to a model.

`implementation` identifies the logical implementation in the delivered
configuration. It is metadata for the binding and documentation; the current
composition root deliberately binds the typed Python implementation explicitly,
rather than importing an arbitrary class named by configuration. This keeps the
composition strongly typed and prevents a configuration file from loading
untrusted code.

The name advertised to the model can therefore be changed independently from
the Python class, but the corresponding capability binding must still exist in
the agent code. An unknown permission, an invalid security declaration or an
undelivered package is refused at load time.

## Configuration capability versus Python skill

There are two related but distinct concepts:

1. A **delivered capability package**, such as
   `config/skills/mail/classify_mail/`, declares how an operation is exposed:
   its tool name, description, security posture, permitted logical MCP tools
   and, when needed, reasoning instructions in `SKILL.md`.
2. A **Python domain skill**, such as
   `agents/mail/src/ai_agent_lab/mail/skills/classification_skill.py`,
   implements the business behavior. It receives typed collaborators through
   dependency injection and does not know which MCP server is behind them.

The relationship is assembled in the composition root, not by letting YAML
instantiate arbitrary Python objects:

```text
config/agents/mail/agent.yaml
    |
    +--> config/skills/mail/classify_mail/skill.yaml
    |       +--> security metadata and tool description
    |       +--> mcp_tools: [get_mail]
    |
    +--> config/skills/mail/classify_mail/SKILL.md
            +--> reasoning instructions

AgentManifestLoader
    |
    v
AgentManifest.skill("classify_mail")
    |
    +--> MailSkillsFactory
    |       +--> MailClassificationSkill(...)
    |       +--> injects the SKILL.md prompt
    |
    +--> MailReadCapabilities
            +--> ClassifyMailInput
            +--> MailClassificationSkill.classify_messages
            +--> SkillDescriptor.from_manifest(...)
```

For `classify_mail`, the runtime call is:

```text
MAF FunctionTool "classify_mail"
    -> SkillToolAdapter
    -> MailReadCapabilities._classify
    -> MailClassificationSkill.classify_messages
    -> MailTools.get_message
    -> TextReasoner
    -> MailClassificationsResult
```

The Python skill is therefore used when the framework invokes the capability
selected by the model. The skill retrieves messages through the `MailTools`
port, builds fenced untrusted context, combines the injected `SKILL.md`
instructions with the injected category catalogue, calls the framework-neutral
`TextReasoner` port and maps the result to typed domain models.

The MCP dependency declared in `skill.yaml` is a logical contract, not a direct
network call. The configured MCP binding and dialect provide the `MailTools`
implementation. Consequently, the same `MailClassificationSkill` can run with
the in-memory mock, the reference MCP server, Gmail or an EWS dialect without
changing the skill.

The distinction is intentional:

```text
skill.yaml / SKILL.md
    = delivery, model-facing description, security and reasoning instructions

mail/skills/*.py
    = typed, reusable domain behavior

mail/capabilities/*.py
    = binding from the delivered capability to the domain skill

framework adapter
    = conversion of the descriptor into FunctionTool, LangChain tool, etc.
```

This is also why `classify_mail` does not apply a mailbox label. Classification
is a read-only domain operation implemented by `MailClassificationSkill`;
`apply_label` is a separate capability implemented through
`MailManagementSkill`, with its own manifest, policy and confirmation behavior.

## Security

`config/` is a **trusted input**. It is delivered by whoever operates the agent,
never by content retrieved from an MCP server, and it must not be writable by a
user of the agent. Everything read from it reaches a prompt unfenced, which is
exactly why it is not the place for anything a third party can influence.

Two things configuration cannot do:

- **Go below the security floor.** Delivering an email is irreversible, so no
  manifest may present `send_mail` as anything but a high-risk operation
  requiring a confirmation. A configuration that tries is refused, loudly, rather
  than silently repaired - a control that fixes itself teaches nobody.
- **Invent a permission.** Permissions are declared by the domain that owns them
  and resolved through a registry, so a typo fails at load time instead of
  quietly granting nothing.

Per-user preferences sit above the delivered defaults and below the floor:

```text
always_confirm (per user) > auto_approve (per user) > manifest default > floor
```

The floor always wins. A future interface letting each user set their own levels
only has to implement `ConfirmationPreferenceStore`.

## MCP bindings

Skills name logical tools. A deployed server exposes whatever names its authors
chose.

```yaml
# config/mcp/mail.yaml
server: mail
tools:
  search_mail: search_mail          # a Gmail server might expose gmail_search
  get_mail: get_mail
```

The binding is checked against the catalogue at load time: a server that does not
cover the contract fails immediately, not on the first request a user makes.

## Reusing the same configuration elsewhere

Manifests carry no framework type. LangChain and CrewAI adapters read the same
`config/` tree, the same skill packages and the same approval defaults, which is
what keeps a framework comparison about the frameworks rather than about three
different configurations.
