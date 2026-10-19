# Use the Wiki Agent

The Wiki Agent answers from online project documentation. It searches and reads
wiki pages through MCP, checks that citations refer to retrieved pages, and
reports when it cannot ground an answer. The local mock mode uses the delivered
sample dataset; it still calls your configured language model.

## Ask a question in mock mode

Install and configure the Wiki Agent using [Get started](getting-started.md),
then start it with `WIKI_AGENT_MODE=mock`:

```powershell
$env:WIKI_AGENT_MODE = "mock"
$env:WIKI_AGENT_USER_ID = "diana"
.\.venvs\wiki-agent\Scripts\wiki-agent.exe --env-file .env_wiki_agent_http
```

Use `--env-file <path>` to load a different configuration file; the default is
`.env`. In VS Code, the Wiki Agent launch profiles ask which file to use. The
selected file is also kept when the HTTP server reloads.

Ask:

```text
What is in scope for the Apollo project?
```

The agent searches the bundled dataset and returns an answer with sources. Try
the same question as `alice`; pages in spaces she cannot read are not used. If
the agent cannot retrieve a page, check the selected user's wiki permissions
and the MCP server's identity configuration.

## Draft and publish

Ask the agent to draft a revision first. `draft_page_content` stores a draft but
does not change the wiki. Then explicitly ask it to publish or update the page.
The write operation shows its target and content and requests confirmation
before execution. A real Confluence MCP deployment also has its own
`WIKI_MCP_READ_ONLY` server-side setting, which must allow writes.

For the complete capability list, grounding behavior, and safe write flow, see
[The Wiki Agent](../../docs/wiki-agent.md). To connect a local or Confluence
server, follow [Running the Wiki Agent](../../docs/wiki-agent-running.md).
HTTP callers can use the example in [Serving the Wiki Agent over HTTP](../../docs/wiki-agent-http.md).
