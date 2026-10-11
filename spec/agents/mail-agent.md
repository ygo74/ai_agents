# Mail agent

## Purpose and role

The Mail agent helps an authenticated mailbox owner find and understand
messages, prepare responses, and perform explicitly requested mailbox changes.
It separates read and analysis skills from operations that change the mailbox so
that a summary or proposal cannot silently become a write.

The application owns mailbox identity, domain models, skills, permission
policy, and the tool port. The selected Microsoft Agent Framework adapter
executes those skills. The shared runtime owns generic conversation handling,
approval limits, and MCP client mechanics. Gmail, a reference dataset, or an
external mail server is reached through a concrete MCP dialect.

## Capabilities

The delivered agent manifest lists the capabilities offered to the model.
Their order is deployment data; an absent skill is not offered.

| Group | Capabilities | Effect |
|---|---|---|
| Find and read | `search_mail`, `get_mail`, `get_thread`, `list_labels` | Search returns bounded headers and previews; separate calls retrieve full messages or a thread. No write. |
| Understand and prepare | `summarise_mail`, `classify_mail`, `extract_mail_actions`, `draft_mail_reply` | Use typed reasoning results. Reply drafting returns a proposal and does not send it. |
| Save drafts and labels | `create_draft`, `create_label` | Changes mailbox state but does not deliver a message. Confirmation is not required by default; policy may require it. |
| Send or organise | `send_mail`, `mark_read`, `archive_mail`, `apply_label`, `remove_label`, `delete_label` | Changes mailbox state. Risk and confirmation requirements come from the delivered operation descriptor, subject to the security floor. |

`create_draft` and `create_label` are low-risk writes that are not confirmed by
default. `send_mail` is always high-risk and must require confirmation; the
security floor rejects a delivered configuration that weakens this rule.
Deleting a label also removes it from messages that use it and is high-risk by
default. Confirmation and permission checks are deterministic and run outside
the model's control.

## Conversation and approval behavior

The HTTP service requires an authenticated caller. Mail operations also require
a verified email address so the application can select the mailbox. Runtime
conversation state is partitioned by caller and conversation; the session uses
server-managed history and does not replay client-supplied history. The current
Mail HTTP entrypoint uses OpenAI Chat Completions.

In a stateless HTTP turn, an operation awaiting a person is not executed. The
application presents a confirmation ticket containing the exact operation
arguments and relevant display details. A later `CONFIRM` or `CANCEL` command is
recognized before the model is invoked. A ticket is bound to its owner and
conversation, expires, and can be claimed once. Confirmation runs the saved
arguments; the model cannot change them between display and execution.

The framework may suspend protected calls during its own execution. The runtime
approval loop bounds approval questions and turns and safely declines remaining
calls on abandonment. The Mail adapter keeps its framework state handling; the
Mail resolver and ticket presenter keep the domain's confirmation meaning.

## Data and security boundaries

Every Mail tool call carries the authenticated user context. The application
does not accept a mailbox identity from message text. The source system or MCP
server applies the caller's data access; the Mail application also checks its
own permissions before writes.

Mail bodies, subjects, sender names, and other values returned by tools are
untrusted input. Skills pass retrieved content to reasoning inside labelled
fences. Audit events record operation outcomes and identifiers, not message
bodies, recipients, or secrets. A model proposal never grants a permission or
confirms a write.

## Runtime modes and acceptance

`mock` uses deterministic in-memory tools and needs no mail service. `mcp` uses
the selected binding and dialect. Both modes use the same skill contracts.

- Search and analysis do not mutate the mailbox.
- Drafting a reply does not deliver it; sending is a separate capability.
- A write runs only after its permission and confirmation rules pass.
- A confirmed write uses the exact arguments shown to the person.
- Caller identity scopes mailbox access, tickets, and conversation state.
- Missing remote tools are not offered as model capabilities.

See [Mail HTTP and approval flow](../../docs/mail-agent-http.md), the
[Mail user guide](../../docs/mail-agent.md), the [MCP boundary](../integrations/mcp-design.md),
and the [server specification](../integrations/mcp-server-hosting.md). The
delivered inventory is in [`agent.yaml`](../../config/agents/mail/agent.yaml);
tool posture is defined by [`catalog.py`](../../agents/mail/src/ai_agent_lab/mail/catalog.py).
