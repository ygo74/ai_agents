# Choose and configure an MCP server

The agents call business systems only through Model Context Protocol (MCP)
servers. A server owns the connection to the wiki or mailbox; the agent uses a
declared tool contract.

## Start with local data

For the Wiki Agent, set `WIKI_AGENT_MODE=mock` to use the in-memory dataset. To
use the repository's reference MCP server over stdio, set
`WIKI_AGENT_MODE=mcp` and `WIKI_MCP_SERVER=wiki-local`. For the Mail Agent,
`MAIL_AGENT_MODE=mock` uses its sample mailbox. These modes need no enterprise
credentials and are the recommended first checks; the model provider is still
external.

For example, start Wiki mock mode from the repository root:

```powershell
$env:WIKI_AGENT_MODE = "mock"
.\.venvs\wiki-agent\Scripts\wiki-agent.exe
```

Ask `What is in scope for Apollo?`; a grounded response with sources shows that
the selected dataset and model are available.

## Connect Confluence

The Wiki Agent supports the community `sooperset/mcp-atlassian` server for
Confluence Cloud and Data Center. The delivered configuration defaults to a
read-only server mode. Follow [Running the Wiki Agent](wiki-agent-running.md)
to choose stdio or streamable HTTP, provide credentials, and map tool names.
See [Wiki MCP server choices](wiki-mcp-servers.md) for compatibility
and the server's security settings.

## Connect Gmail

The Mail Agent can use the reference dataset or a Gmail-backed MCP server. The
official Google-hosted MCP service and the repository's Gmail API server have
different setup and credential requirements. Start with
[Mail MCP server options](mail-mcp-servers.md); it explains OAuth
consent, API scopes, and the HTTP network boundary.

## Keep identity and access aligned

An MCP server must enforce its own access checks. For a wiki, the configured
transport must preserve the caller's identity or deliberately act as one named
account. For a mailbox, grant only the required Google scopes and keep the MCP
server port private. Never put credentials in prompts or commit them to the
repository.
