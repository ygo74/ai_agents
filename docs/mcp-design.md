# MCP Design

## 1. Role of MCP in this repository

MCP is the integration boundary between agents and enterprise systems. Agents
and skills know a typed tool contract; they never know how it is implemented.

```text
Skill  ->  MailTools (Protocol)  ->  McpMailTools  ->  MCP client
                                                          |
                                                          v
                                                    Mail MCP Server
                                                          |
                                                          v
                                                        Gmail
```

Whether the server uses the Gmail API, Microsoft Graph, EWS, IMAP or SMTP is
invisible above the contract, by design.

## 2. Contract layer (`mcp/mail`)

The contract layer contains no implementation:

| Module         | Content                                                    |
|----------------|------------------------------------------------------------|
| `contracts.py` | `MailTools` Protocol - the tool surface                     |
| `catalog.py`   | `MailToolCatalog` - operation type, risk, descriptions      |
| `errors.py`    | `McpToolError` hierarchy raised across the boundary         |

Every operation has a typed input model and a typed output model taken from
`domain/mail`. Raw dictionaries never cross the boundary.

## 3. Mail tool surface

One generic search capability covers every search variation; the variation is
carried by `MailSearchRequest`, not by a proliferation of tools.

| Tool            | Type  | Risk   | Confirmation | Input -> Output                          |
|-----------------|-------|--------|--------------|------------------------------------------|
| `search_mail`   | READ  | LOW    | no           | `MailSearchRequest` -> `MailSearchResult`|
| `get_mail`      | READ  | LOW    | no           | `message_id` -> `MailMessage`            |
| `get_thread`    | READ  | LOW    | no           | `thread_id` -> `MailThread`              |
| `list_labels`   | READ  | LOW    | no           | - -> `list[MailLabel]`                   |
| `create_draft`  | WRITE | LOW    | no (default) | `MailDraft` -> `MailDraft`               |
| `send_mail`     | WRITE | HIGH   | yes          | `MailSendRequest` -> `MailSendResult`    |
| `mark_read`     | WRITE | LOW    | yes (default, configurable) | `message_id`, `is_read` -> none |
| `archive_mail`  | WRITE | MEDIUM | yes          | `message_id` -> none                     |
| `apply_label`   | WRITE | MEDIUM | yes          | `message_id`, `label` -> none            |
| `remove_label`  | WRITE | MEDIUM | yes          | `message_id`, `label` -> none            |

`create_draft` mutates the mailbox but sends nothing, so it is a low-risk write
that does not require confirmation by default. It remains configurable.

## 4. Tool descriptions

Descriptions are part of the contract because the model uses them to select a
tool. They must state what the tool does, what it does not do, and whether it
has side effects. Ambiguous descriptions are a correctness bug, not a cosmetic
issue.

## 5. Implementations

| Implementation      | Location                        | Purpose                     |
|---------------------|---------------------------------|-----------------------------|
| `InMemoryMailTools` | `infrastructure/inmemory`       | deterministic dataset, tests|
| `McpMailTools`      | `infrastructure/mcp`            | real MCP server             |

Both are validated by the same conformance suite in `tests/contract`, so a mock
run and a real run exercise identical semantics.

## 6. Error translation

MCP transport and protocol errors never leak upwards. `McpMailTools` translates
them into domain-meaningful exceptions:

| Situation                        | Exception                  |
|----------------------------------|----------------------------|
| unknown message / thread         | `MailNotFoundError`        |
| caller not allowed by the source | `MailAccessDeniedError`    |
| server unreachable / timeout     | `MailToolUnavailableError` |
| malformed or unexpected payload  | `MailToolProtocolError`    |

Payload validation is strict: an unexpected shape is an error, never a silently
accepted partial result.

## 7. Security

- credentials live in the MCP server / infrastructure layer and are never
  placed in prompts, in `UserContext`, in logs or in tool results;
- authorisation is enforced by the source system and re-checked deterministically
  in the application layer; the model never authorises anything;
- every call carries the caller identity so the server can scope results;
- all returned content is untrusted data and is wrapped as `UntrustedText`.

## 8. Separation of concerns

MCP protocol handling, domain logic and agent reasoning stay separate:

- `mcp/` declares contracts only;
- `infrastructure/mcp/` speaks the protocol and maps payloads;
- `skills/` applies business rules;
- `frameworks/` adapts to an agent framework.

## 9. Client API in use

The Microsoft Agent Framework adapter uses the MCP client shipped with the
framework (`MCPStdioTool` for local servers, `MCPStreamableHTTPTool` for HTTP
servers). The MCP client is an infrastructure detail: `McpMailTools` owns it and
exposes only `MailTools`.

## 10. Mail MCP server

The Gmail-backed Mail MCP server is a separate deliverable. Until it exists, the
contract is honoured by `InMemoryMailTools` and the mock runtime mode. No Gmail
code is ever added above the contract to compensate.
