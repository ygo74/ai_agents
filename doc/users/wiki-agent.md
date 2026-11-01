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

For an explicit request to create or update a page, the agent prepares a draft
and proposes the write in the same turn. `draft_page_content` stores a draft but
does not change the wiki. The write operation shows its target and a content
preview, then requests the one required confirmation before execution. There is
no separate question about publishing the draft first.

For example, in the same LibreChat conversation:

1. Ask: "Update the Architecture overview page to add a Live test section."
2. Review the proposed change and reply `CONFIRM <ticket-id>` with the ticket
   supplied by the agent. Use `CANCEL <ticket-id>` to decline instead.
3. The confirmed operation updates the page and returns its new version.

The HTTP reply after confirmation is a readable acknowledgement, not raw tool
JSON or the model's internal `UNTRUSTED` blocks. For example, a successful page
update can return:

```text
Page saved successfully.

- Title: Architecture overview
- Page: apollo-architecture
- Space: APOLLO
- Version: 3
```

The actual page identifier, space, and version come from the completed write.
The reply also includes an "Open page" link when the wiki returns a valid HTTP
or HTTPS URL without credentials. Page titles are displayed as text, not active
HTML or Markdown. The internal tool results sent to the model still keep their
untrusted-content protections. Confirmed deletions and comments also return
short acknowledgements. These replies work with and without streaming, and do
not invoke the model or ask for another confirmation.

A general "yes" is not a substitute for the ticket command. If you ask only for
a draft or preview, the agent shows the draft without proposing a write. Ask it
to publish that draft when you are ready; the same confirmation rule applies.
A real Confluence MCP deployment also has its own `WIKI_MCP_READ_ONLY`
server-side setting, which must allow writes.

For the complete capability list, grounding behavior, and safe write flow, see
[The Wiki Agent](wiki-agent-reference.md). To connect a local or Confluence
server, follow [Running the Wiki Agent](wiki-agent-running.md).
HTTP callers can use the example in [Serving the Wiki Agent over HTTP](wiki-agent-http.md).
