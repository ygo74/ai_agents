# Use the Mail Agent

The Mail Agent finds, reads, summarizes, and classifies messages. It can also
draft replies and apply labels. It asks for confirmation before an operation
that changes the mailbox. Use mock mode first to try the workflow against the
delivered sample mailbox.

## Start with the sample mailbox

Install the Mail Agent environment from the repository root:

```powershell
py -3.12 -m scripts.install --env mail-agent --into .venvs\mail-agent
Copy-Item .env.example .env
```

Set the model provider variables in `.env`, then run:

```powershell
$env:MAIL_AGENT_MODE = "mock"
.\.venvs\mail-agent\Scripts\python.exe -m ai_agent_lab.mail.application
```

Ask `anything from John?`. The agent searches the sample mailbox and summarizes
matching messages. The mock mailbox needs no Gmail credential; the configured
language model still needs its own provider credential.

## Try a confirmed operation

Ask the agent to apply a label to a message. It returns a confirmation request
with the message, sender, and label. Reply with the exact `CONFIRM cfm-...`
command to apply it, or `CANCEL cfm-...` to decline. In HTTP mode, keep the same
conversation ID when answering the ticket.

Use [Serving the Mail Agent over HTTP](../../docs/mail-agent-http.md) for an API
example. The complete list of tools, permissions, and confirmation behavior is
in [Mail Agent](../../docs/mail-agent.md). To connect a real mailbox, start with
[Mail MCP server options](../../docs/mail-mcp-servers.md).
