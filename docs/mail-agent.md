# Mail Agent

The first agent of the laboratory. It assists the owner of a mailbox and, above
all, it exists to prove one architectural property:

```text
User -> Mail Agent -> Skill -> MCP Tool -> Mail MCP Server -> Gmail
```

The agent, the skills and the domain contain no Gmail, OAuth, IMAP or SMTP
knowledge. That is enforced by `tests/architecture/test_layer_boundaries.py`,
not by convention.

## 1. Capabilities

| Tool exposed to the model | Type  | Confirmation | What it does |
|---------------------------|-------|--------------|--------------|
| `search_mail`             | READ  | no           | Finds messages by sender, recipient, subject, keywords, label, date range, unread state or attachments, alone or combined. Returns previews. |
| `get_mail`                | READ  | no           | Retrieves one complete message. |
| `get_thread`              | READ  | no           | Retrieves a whole conversation. |
| `list_labels`             | READ  | no           | Lists the labels of the mailbox, so label operations can name a real identifier. |
| `summarise_mail`          | READ  | no           | Summarises a message or a conversation: key points, decisions, actions, deadlines, participants, open questions, sources. |
| `classify_mail`           | READ  | no           | Assigns one configurable category per message, with confidence and reason. |
| `extract_mail_actions`    | READ  | no           | Lists what the owner has to do, marking each action explicit or inferred. |
| `draft_mail_reply`        | READ  | no           | Prepares a reply and returns a draft reference. Sends nothing. |
| `send_mail`               | WRITE | **always**   | Delivers a prepared draft, identified by its reference. |
| `mark_read`               | WRITE | yes (configurable) | Marks a message read or unread. |
| `archive_mail`            | WRITE | yes          | Removes a message from the inbox. |
| `apply_label`             | WRITE | yes          | Attaches a label. |
| `remove_label`            | WRITE | yes          | Detaches a label. |

## 2. Skills

Skills hold the domain logic and know nothing about any agent framework.

| Skill | Responsibility |
|---|---|
| `MailSearchSkill` | Turns a structured request into a mailbox query. |
| `MailReadSkill` | Retrieves a message, several messages or a conversation. |
| `MailSummarySkill` | Summarises, grounded in the retrieved messages. |
| `MailClassificationSkill` | Assigns a category from an injected catalogue. |
| `MailActionExtractionSkill` | Extracts actions, separating stated from deduced. |
| `MailReplySkill` | Drafts a reply. Never sends. |
| `SendMailSkill` | Saves drafts and delivers them once approved. |
| `MailManagementSkill` | Read state, archiving and labels. |

Collaborators worth naming: `MailContextBuilder` assembles the untrusted
context, `MailAnalysisMapper` maps model output to domain models and enforces
grounding, `ReplyRecipientPlanner` decides recipients deterministically, and
`GatedMailOperationRunner` applies permission, confirmation and audit to every
state-changing operation.

## 3. Deterministic before generative

Anything that can be computed reliably is computed in code:

- filtering, sorting and paging of search results;
- who a reply is addressed to, and the exclusion of the mailbox owner;
- whether an operation needs a confirmation;
- the category vocabulary and the fallback when a proposal is unknown;
- the confidence clamping and the source grounding of every analysis.

The model is used where it adds value: summarising, classifying, spotting
actions and wording a reply.

## 4. Confirmation model

Two independent guards, so the rule survives a change of orchestration:

1. **Framework guard.** The adapter registers a gated tool with
   `approval_mode="always_require"`, so Microsoft Agent Framework suspends the
   call and reports it in `AgentResponse.user_input_requests`. The console
   resolves the raw arguments into a full description - recipients, subject,
   body - and asks. Anything that is not an explicit yes is a refusal.
2. **Domain guard.** `SendMailSkill` and `MailManagementSkill` re-check the
   policy themselves through `ConfirmationGate` and raise
   `ConfirmationRequiredError` without a valid decision. A skill invoked from a
   script, a test or another framework is gated just the same.

### Configuring it

The policy is data driven and resolved per user:

```text
always_confirm (per user)  >  auto_approve (per user)  >  tool default
```

A risk floor sits above all of that: operations at or above
`non_overridable_risk` - `HIGH` by default - always require a confirmation, so
a preference file can never silently disarm sending an email.

```bash
# .env
MAIL_AGENT_AUTO_APPROVED_TOOLS=mark_read
MAIL_AGENT_ALWAYS_CONFIRM_TOOLS=create_draft
```

Preferences are stored per user through `ConfirmationPreferenceStore`, so
per-user settings become a matter of implementing that port against a database.

### Draft references

`draft_mail_reply` returns an opaque reference; `send_mail` takes that reference
and nothing else. The content delivered is therefore exactly the content the
user approved: a model cannot rewrite recipients or body between the two turns.
References are scoped to their owner and cannot be redeemed by another user.

## 5. Security

- **Identity.** Every operation carries a `UserContext`. It holds an identity
  and permissions, never a credential.
- **Authorisation.** Permissions are checked by code before anything runs. The
  source system remains the authority; the model authorises nothing.
- **Untrusted content.** Everything from MCP is `UntrustedText`, whose `repr`
  hides the payload so logging cannot leak a message. Reading the payload is an
  explicit `expose()` call.
- **Prompt injection.** Third-party content is fenced with a unique
  per-rendering delimiter, embedded delimiters are neutralised, and the prompt
  states that fenced material is data. The same fence is applied to reasoning
  prompts *and* to tool results, so reading a message with the agent is no
  weaker than analysing it with a skill.
- **Grounding.** An analysis referencing a message that was not in the context
  is rejected, so untrusted content cannot fabricate a source.
- **Audit.** Every state-changing attempt is recorded with its outcome:
  executed, declined, blocked or failed. Records hold identifiers only - no
  body, no subject, no recipient.

The structural guarantee matters more than the prompt: no model output reaches
a side effect without passing the deterministic confirmation policy.

## 6. Running it

### Setup

One virtual environment per agent and per framework:

```powershell
py -3.12 -m venv .venvs\mail-agent-maf
.\.venvs\mail-agent-maf\Scripts\python.exe -m pip install -e ".[maf,dev]"
Copy-Item .env.example .env
```

### Mock mode - no Gmail, no mail credentials

```powershell
$env:MAIL_AGENT_MODE = "mock"
$env:OPENAI_API_KEY  = "<your key>"
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.application.mail
```

```text
Mail Agent ready.

You > Find unread emails from the last week.
Agent > ...

You > Draft a reply to John saying I will review the document tomorrow.
Agent > I prepared this draft: ...

You > Send it.

[confirmation] Send this email?
  operation: send_mail (HIGH risk)
  To: john.smith@example.com
  Subject: Re: Project Alpha - architecture review
  Body: ...
  approve? [y/N] y
  -> approved

Agent > Email sent.
```

The mailbox comes from `data/mail/sample_mailbox.json`. It contains a project
conversation, an invoice, a newsletter, a prompt-injection attempt and a second
mailbox used to test isolation.

### MCP mode

`MAIL_AGENT_MODE=mcp` is wired through `MailToolsProvider` and currently fails
with an explicit message: the Gmail-backed Mail MCP server is the next
deliverable. When it exists, only `McpMailTools` is added; the agent, the skills
and the scenarios do not change. That is the point of the mode split.

## 7. Testing

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m pytest tests -q
.\.venvs\mail-agent-maf\Scripts\python.exe -m pytest tests -q -m security
.\.venvs\mail-agent-maf\Scripts\python.exe -m pytest tests -q -m scenario
```

| Suite | What it proves |
|---|---|
| `tests/unit` | Domain invariants, the confirmation decision table, each skill in isolation. |
| `tests/contract` | Any `MailTools` implementation behaves identically. The suite is written against the contract, so the future MCP client reuses it unchanged. |
| `tests/agent` | Scenarios MAIL-001 to MAIL-006, run against the real agent, the real tools and the real approval middleware, with a scripted model. |
| `tests/security` | Cross-mailbox access, confirmation bypass, authorisation, prompt injection and data leakage. |
| `tests/architecture` | Layer boundaries, absence of framework imports in the business layers, absence of mail SDKs anywhere but infrastructure. |

No test needs a network, an API key or a mailbox.

The scenarios are also described in `scenarios/mail/scenarios.yaml`, in a form
that stays valid when the same cases are replayed against LangChain and CrewAI.

## 8. Preparing the framework comparison

Reusing the Mail Agent with another framework means writing one adapter that:

1. turns a `SkillDescriptor` into that framework's tool type;
2. maps `ToolOperationDescriptor` onto its approval mechanism;
3. implements `TextReasoner` with its chat abstraction.

Nothing else moves. Domain models, skills, MCP contracts, the confirmation
policy, the datasets and the scenarios are shared, which is the only way the
measurements - correctness, tool selection, grounding, latency, tool calls,
tokens, implementation complexity, testability - compare frameworks rather than
three different implementations.

## 9. Known limitations

- The Gmail Mail MCP server does not exist yet; only the mock mode runs.
- Drafts and confirmation preferences live in memory, for the lifetime of a
  process.
- A summary is produced from fenced content but is itself relayed to the agent
  as text. It is labelled as derived from untrusted material; a stricter
  treatment is possible if a scenario justifies it.
- `agent_framework.security` (FIDES) offers information-flow labels that would
  strengthen the injection posture. It is experimental and deliberately left for
  a later phase.
