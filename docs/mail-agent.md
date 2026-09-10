# Mail Agent

The first agent of the laboratory. It assists the owner of a mailbox and, above
all, it exists to prove one architectural property:

```text
User -> Mail Agent -> Skill -> MCP Tool -> Mail MCP Server -> Gmail
```

The agent, the skills and the domain contain no Gmail, OAuth, IMAP or SMTP
knowledge. That is enforced by `tests/architecture/test_distribution_boundaries.py`,
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
| `draft_mail_reply`        | READ  | no           | Prepares a reply and returns a draft reference. Stores nothing and sends nothing. |
| `create_draft`            | WRITE | no (configurable) | Saves a prepared reply into the mailbox drafts. Delivers nothing. |
| `send_mail`               | WRITE | **always**   | Delivers a prepared draft, identified by its reference. |
| `mark_read`               | WRITE | yes (configurable) | Marks a message read or unread. |
| `archive_mail`            | WRITE | yes          | Removes a message from the inbox. |
| `apply_label`             | WRITE | yes          | Attaches a label to a message. |
| `remove_label`            | WRITE | yes          | Detaches a label from a message. |
| `create_label`            | WRITE | no (configurable) | Makes a label exist, so messages can be filed under it. Returns the existing one if the name is taken. |
| `delete_label`            | WRITE | yes (configurable) | Deletes a label from the mailbox, and from every message carrying it. Irreversible. |
Searching by label needs no tool of its own: `search_mail` takes `label_ids`.
Several labels **narrow** the search to messages carrying all of them, which is
what Gmail, IMAP and a filter UI all do.

`create_label` and `delete_label` sit at opposite ends on purpose. Creating a
label destroys nothing and is undone by deleting it, so it is not gated by
default. Deleting one is irreversible, and its blast radius is the whole mailbox
rather than a single message: nothing records which messages carried the label,
so the operation cannot be walked back even manually. That is why it is HIGH
risk, like sending.

Neither is written into the security floor, so a deployment can change both in
`config/skills/mail/`. Only `send_mail` is beyond a configuration's reach.

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
| `MailManagementSkill` | Read state, archiving, labels on messages, and the label set itself. |

Each capability is delivered as a package under `config/skills/mail/`: a
`skill.yaml` declaring its identity, security posture and the MCP tools it may
use, plus a `SKILL.md` carrying the prompt when a model is involved. The prompt
is injected into the skill, so re-wording a summary is a configuration delivery.
See [configuration.md](./configuration.md).

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

Independent, but not differently informed. Both read the posture from the
delivered skill package, through `DeliveredMailOperations`. `MailToolCatalog`
holds what the *code* proposes; a package may change it, within what
`MailSecurityFloor` allows, and what the deployment runs under is read back from
the manifest.

That single source is not a tidiness preference. When the two guards read
different sources, a capability ungated in configuration becomes one the
framework never asks about *and* the domain always refuses — impossible to
perform, and reported to the model as a mailbox refusal.
`tests/integration/test_delivered_posture.py` pins it.

### One request, from the prompt to the audit trail

The request the user reads is the request that authorises the call and the
request recorded in the audit trail. It travels through a `ConfirmationLedger`,
keyed by capability and target and scoped to its owner:

```text
framework suspends send_mail(draft_reference=X)
        -> presenter builds request R (recipients, subject, body)
        -> console shows R, user answers
        -> ledger records (R, decision) for this user
        -> framework resumes and invokes the tool
        -> broker takes (R, decision) from the ledger
        -> ConfirmationGate enforces R, audit records R.request_id
```

An entry is consumed once, so one approval can never authorise two executions,
and it is scoped to a user, so it can never authorise an operation on another
mailbox. When nothing was recorded, `UnattendedApprovalAuthority` refuses rather
than approving on the framework's behalf.

`ConfirmationGate` additionally checks that the request was issued for the
calling user and that the decision was made by them. An answer collected for one
mailbox cannot authorise anything in another.

### What the prompt shows

A model works with identifiers; a person does not. Asked to approve
`apply_label` on `1a0027bd9c6c5d17` with `Label_5`, nobody is really being asked
anything, and the only informed answer is no. So the presenter resolves the
identifiers before asking:

```text
[confirmation] Apply this label to the message?
  operation: apply_label (MEDIUM risk)
  reference: cfm-2181958ca254
  Message: m-alpha-1
  Subject: Project Alpha - architecture review
  From: john.smith@example.com
  Label: Project Alpha (PROJECT_ALPHA)
  approve? [y/N/a=all of this kind]
```

The identifiers stay, because they are what gets enforced and audited; the
readable facts sit next to them. A lookup that fails leaves the identifier alone
rather than guessing — a confirmation that misdescribes an operation is worse
than one that under-describes it — and the prompt is still shown. Subjects are
written by whoever sent the message, so they remain fenced as untrusted content.

### Answering once for a whole kind

Asked the same question about twenty messages, a person stops reading it, and
the safeguard becomes a formality. Answering `a` therefore approves every
further operation **of that capability** for the rest of the conversation.

What it does not change:

- each operation still gets its own request, its own decision and its own audit
  record. The standing answer removes the question, never the trace;
- it is scoped to one capability and one conversation. Approving every
  `apply_label` says nothing about `archive_mail`, and nothing survives a restart;
- it is only offered for capabilities the security floor leaves overridable, so
  `send_mail` never gets the choice — and answering `a` there is read as a
  refusal rather than silently honoured.

### Interrupted turns

The framework does not run a batch of gated calls until every one of them has
been answered, and it keeps the answers already given in the session. A turn
that simply walked away from a long batch would let the next, unrelated turn
complete it and execute calls the user approved under a different premise.

When a turn exceeds its budget, the session therefore drops the recorded answers
first and only then refuses what is left. The batch completes with no decision
available, the domain gate refuses every call, and nothing further is executed.
This is covered by `tests/agent/test_mail_scenarios.py`.

There are two budgets, and they guard different things:

- **questions asked** (25). A request that interrogates somebody twenty-five
  times has gone wrong whatever it is doing. A round auto-approved by a standing
  answer asks nobody anything and does not count — otherwise saying "yes to all
  of these" would silence the questions and interrupt the turn anyway.
- **rounds of any kind** (200), so a runaway loop still ends.

What the budget stops is the questioning. Operations approved and executed
before the limit stay executed; only what is pending is refused.

### When a turn fails

A turn can fail for reasons that have nothing to do with the mailbox — the model
provider refusing a request is the common one. That ends the turn, not the
conversation: the failure is reported in one sentence, the detail goes to the
log, and the session continues with its drafts intact.

A refusal is also logged as a refusal. A gated call the domain gate refuses
returns explanatory text to the model, which is a perfectly normal return as far
as the framework is concerned — its own log then reads `Function apply_label
succeeded`. Without our own line, an operator would read a column of successes
and an unchanged mailbox.

### Configuring it

The policy is data driven and resolved per user:

```text
always_confirm (per user)  >  auto_approve (per user)  >  manifest default
```

Above all of that sits the **security floor**, and only the floor. Risk level
says how much an operation costs; the floor says what a configuration may not
touch. Keeping them separate matters: describing an operation honestly as HIGH
should not quietly take it away from the person whose mailbox it is. Today the
floor protects one operation, `send_mail`, and the delivered manifests cannot
weaken it either — `config/skills/mail/send_mail/skill.yaml` declaring a lower
risk is refused at load time.

Everything else is yours to decide, in either of two places.

Per user, in `.env` — a comma-separated list of capability names:

```bash
# .env
MAIL_AGENT_AUTO_APPROVED_TOOLS=apply_label,remove_label,mark_read
MAIL_AGENT_ALWAYS_CONFIRM_TOOLS=create_draft
```

Or as the delivered default for a deployment, in the skill package:

```yaml
# config/skills/mail/apply_label/skill.yaml
operation:
  confirmation_required: false
```

Change `confirmation_required` and nothing else. `risk` describes what the
operation costs: it is shown in the prompt and recorded in the audit trail, and
lowering it makes both less truthful without loosening anything.

The `.env` route is per user and wins over the package default, which is why it
is the one to reach for while trying things out. Per-user overrides go through
`ConfirmationPreferenceStore`, so a future interface letting each person choose
their own levels only has to implement that port.

### Draft references

`draft_mail_reply` returns an opaque reference; `create_draft` and `send_mail`
take that reference and nothing else. The content saved or delivered is
therefore exactly the content the user approved: a model cannot rewrite
recipients or body between the two turns. References are scoped to their owner
and cannot be redeemed by another user.

Composing, keeping and delivering are three capabilities rather than one because
they have three different consequences. Drafting touches nothing, so it needs no
approval. Saving puts something in the mailbox that nobody receives. Sending is
irreversible, and is the only one the security floor gates unconditionally.

Saving does not consume the reference: a draft kept in the mailbox can still be
sent afterwards. What is delivered is then the stored draft, so the mailbox keeps
its own copy - the two are the same content, not the same object.

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
.\.venvs\mail-agent-maf\Scripts\python.exe -m scripts.install
Copy-Item .env.example .env
```

The script installs every distribution in editable mode, in dependency order,
including the Entra ID support used when authenticating to Azure OpenAI.

### Model provider - OpenAI or Azure OpenAI

`AGENT_CHAT_PROVIDER` selects the provider. Only the client object changes: the
agent, the skills, the MCP contract and the confirmation policy are identical.

```bash
# .env - OpenAI
AGENT_CHAT_PROVIDER=openai
OPENAI_API_KEY=<key>
OPENAI_CHAT_MODEL=gpt-4o-mini
```

```bash
# .env - Azure OpenAI with a key
AGENT_CHAT_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_CHAT_MODEL=<deployment name>
AZURE_OPENAI_API_KEY=<key>
```

```bash
# .env - Azure OpenAI with Entra ID, no key at all
AGENT_CHAT_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_CHAT_MODEL=<deployment name>
AZURE_OPENAI_CREDENTIAL=azure_cli
```

`AZURE_OPENAI_CHAT_MODEL` is the **deployment** name. `AZURE_OPENAI_ENDPOINT`
accepts the resource URL as well as the complete `.../openai/v1` form shown by
the portal: the trailing segment is normalised, so the path is never duplicated.
`AZURE_OPENAI_BASE_URL` is deliberately refused - the client cannot combine it
with an endpoint, and it would silently fall back to the OpenAI path where the
Azure key is never read. `AZURE_OPENAI_CREDENTIAL` accepts `api_key`,
`azure_cli` or `default`.

There is no separate Azure client to install: the installed Agent Framework
serves both providers through the same `agent_framework.openai` clients, and the
Python `AzureOpenAI*` classes were removed from `agent_framework.azure`. Azure is
reached by passing explicit routing inputs.

The provider is declared rather than deduced for one concrete reason: the
unified client stays on OpenAI whenever `OPENAI_API_KEY` is set, even when every
`AZURE_OPENAI_*` variable is filled in - which is exactly what copying
`.env.example` produces. Deducing it would silently ignore an Azure deployment.
`tests/integration/test_chat_client_selection.py` pins that behaviour.

No key is ever read, stored or logged by the application. With `api_key` the
framework client resolves it from the environment; with Entra ID it receives a
credential object and exchanges it for a token itself.

`.env` is loaded into the process environment at startup without overriding
anything already set, so a real environment variable always wins over the file
and both the settings and the chat client see the same values.

### Mock mode - fake MCP, no Gmail, no mail credentials

The repository already contains a deterministic fake for the Mail MCP boundary:
`InMemoryMailTools` implements the same typed `MailTools` contract that a future
MCP client will implement. It is not a Gmail emulator and it does not start a
network MCP server; it is an in-process test double backed by a JSON mailbox.
The agent, skills and confirmation policy use it through the same contract as
the future Mail MCP implementation.

```powershell
$env:MAIL_AGENT_MODE = "mock"
$env:OPENAI_API_KEY  = "<your key>"
$env:OPENAI_CHAT_MODEL = "gpt-4o-mini"
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.application
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

To use another deterministic mailbox, provide a JSON file with the same
`mailboxes` structure and set its path relative to the repository root:

```powershell
$env:MAIL_AGENT_MODE = "mock"
$env:MAIL_AGENT_MOCK_DATASET = "data/mail/my_mailbox.json"
$env:OPENAI_CHAT_MODEL = "gpt-4o-mini"
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.application
```

### VS Code debug

`.vscode/launch.json` provides six configurations, all using
`.venvs\mail-agent-maf\Scripts\python.exe`:

| Configuration | What it forces |
|---|---|
| **Mail Agent (.env decides)** | nothing — the backend comes from `.env` |
| **Mail Agent (force mock dataset)** | `MAIL_AGENT_MODE=mock` |
| **Mail Agent (force the reference MCP server)** | `MAIL_AGENT_MODE=mcp`, `MAIL_MCP_SERVER=local` |
| **Mail Agent (force the Gmail API MCP server)** | `MAIL_AGENT_MODE=mcp`, `MAIL_MCP_SERVER=gmail-api` |
| **Authorise the Gmail API server** | one-off Google consent for our Gmail server |
| **Authorise against the official Gmail MCP server** | one-off consent for the hosted Google server |

The `env` block of a launch configuration **overrides** `envFile`, so the
"force" configurations win over `.env` by design. Pick **(.env decides)** when
you want the file to be the single source of truth — that is the configuration
to use if you ever wonder why the mock keeps running.

Create `.env` from `.env.example` first and set the model provider credentials
there. No launch configuration contains a credential.

The interactive CLI uses Microsoft Agent Framework and therefore needs the
configured model provider key. The fake MCP itself needs no key, network access
or mail credentials. The contract and agent scenarios use scripted doubles and
can be run completely offline:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m pytest tests\contract tests\agent tests\security -q
```

### MCP mode

`MAIL_AGENT_MODE=mcp` runs the agent against a real mail MCP server, selected by
`MAIL_MCP_SERVER`. The reference server needs nothing but the repository:

```powershell
$env:MAIL_AGENT_MODE = "mcp"
$env:MAIL_MCP_SERVER = "local"
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.application
```

Against a real mailbox, consent once and then run. The Google credential lives
in the server process alone; the agent talks to it over stdio and never sees a
token:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m mail_mcp.gmail.authorise

$env:MAIL_AGENT_MODE = "mcp"
$env:MAIL_MCP_SERVER = "gmail-api"
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.application
```

The agent, the skills and the scenarios are identical in both modes; only the
object built by the provider changes. Which servers exist, what the official
Google Gmail server can and cannot do, and how to plug in another one are
covered in [mail-mcp-servers.md](./mail-mcp-servers.md).

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

- The official Gmail server has no send tool and no per-message retrieval, so
  those capabilities are not offered when it is the bound server. See
  [mail-mcp-servers.md](./mail-mcp-servers.md).
- Drafts and confirmation preferences live in memory, for the lifetime of a
  process.
- A summary is produced from fenced content but is itself relayed to the agent
  as text. It is labelled as derived from untrusted material; a stricter
  treatment is possible if a scenario justifies it.
- `agent_framework.security` (FIDES) offers information-flow labels that would
  strengthen the injection posture. It is experimental and deliberately left for
  a later phase.
