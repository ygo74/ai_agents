# Running the Wiki Agent

Three ways to run it, in increasing order of what they need from you. Start at
the top.

| | Needs | Reaches |
|---|---|---|
| `mock` | a model provider | `data/wiki/sample_wiki.json`, in memory |
| `wiki-local` | a model provider | the same dataset, over a real MCP stack |
| `mcp-atlassian` | a model provider, Docker, a Confluence token | your real Confluence |

## 1. Install

Each agent has its own virtual environment. That is not tidiness: installing
LangChain alongside Microsoft Agent Framework has already been observed to move a
shared dependency under the other's feet.

```powershell
py -3.12 -m scripts.install --env wiki-agent --into .venvs\wiki-agent
```

Add the development environment too if you want to run the tests:

```powershell
py -3.12 -m scripts.install --env dev --into .venvs\dev
```

## 2. Configure

```powershell
Copy-Item .env.example .env
```

Then fill in **two things** for the mock mode:

```bash
AGENT_CHAT_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_CHAT_MODEL=gpt-4o-mini
```

The model settings are shared with the Mail Agent on purpose: both agents must
run against the same model, or a comparison between the two frameworks measures
two different deployments rather than two frameworks.

No API key is ever read, held or logged by the application. The LangChain client
resolves it from the environment itself.

## 3. Run

From VS Code, press **F5** and pick a configuration from `.vscode/launch.json`:

| Configuration | What it exercises |
|---|---|
| **Wiki Agent — mock dataset** | the agent, the skills, the framework. No MCP at all. |
| **Wiki Agent — reference MCP server** | the above, plus a real stdio transport, a real handshake, the binding and the native dialect |
| **Wiki Agent — Confluence** | the above, against a real wiki, through `mcp-atlassian` |
| **Wiki MCP reference server** | the server alone, to inspect its payloads |
| **Tests — wiki agent** | domain, MCP client, dialects, skills, security |

Or from a terminal:

```powershell
.\.venvs\wiki-agent\Scripts\wiki-agent.exe
```

Things worth asking it against the delivered dataset:

```text
What is in scope for the Apollo project?
Summarise the architecture page.
Which pages in APOLLO have gone stale?
Is Apollo over budget?
```

The last one is the interesting one. Set `WIKI_AGENT_USER_ID=alice` and the
answer changes, because `alice` cannot read the `BOARD` space where the budget
review lives. Set it back to `diana` and the page appears. That is the
authorisation model working, and it is worth seeing once.

Try also: *"read the onboarding page"*. That page carries a planted instruction
telling the agent to dump the `BOARD` space and delete the decision log. It
should be reported as a suspicious instruction, not followed. In `mock` mode the
write capabilities are live against the in-memory dataset, so this is also the
cheapest way to watch the confirmation prompt refuse to appear for an operation
nobody asked for.

## 4. Writing to the wiki

The agent can draft and publish pages and comments. Two things are worth knowing
before trying it.

**Composing never writes.** Ask for *"draft a revision of the architecture page
mentioning the new queue"* and the agent calls `draft_page_content`, which
composes a body, stores it and shows it to you. Nothing has reached the wiki. Ask
it to publish, and `update_page` takes the stored draft — not a body the model
supplies a second time — so what is written is what you read.

**Every write asks first.** The console prints the operation, its risk, the page
and the body, then waits:

```text
Replace the content of this page?
  Operation: update_page (risk: high)
  Page: apollo-architecture
  New body: ...
  Replaces version: 2
Allow it? [y/N]
```

Anything that is not an explicit `y` is a refusal. `update_page` and
`delete_page` always ask, whatever the configuration says; `add_comment` and
`create_page` ask by default and a deployment may decide otherwise.

Against a real Confluence there is a second switch. `.env.example` ships
`WIKI_MCP_READ_ONLY=true`, so the server itself refuses writes until you set it
to `false` deliberately. The full reasoning is in
[wiki-agent.md](./wiki-agent.md#writing-to-the-wiki).

---

# Configuring the MCP server

## Which server, and why

**`sooperset/mcp-atlassian`**, pinned to **v0.23.1 or later**. It is the only
mature MCP server covering Confluence Cloud *and* Confluence Data Center behind
one identical tool surface, which is what makes the eventual move from the lab to
the office a change of environment variables rather than a rewrite.

The full comparison, the servers that were rejected and the security advisories
behind the version pin are in [wiki-mcp-servers.md](./wiki-mcp-servers.md).

## Where the configuration lives

Three files, and they answer three different questions:

```text
config/mcp/mcp-atlassian.yaml    what the server is and what it can do
.env                             which server to use, and the credentials
.vscode/launch.json              what a debug session sets on top
```

### `config/mcp/<server>.yaml` — the binding

This is delivered configuration, committed to the repository. It declares:

- **how to reach the server** — `transport`, `command`, `args`;
- **which of our capabilities it can actually serve** — `capabilities`;
- **the name it gives to each tool** — `tools`;
- **which dialect translates it** — `dialect`;
- **the environment variables it needs** — `env`, by *name only*.

A capability the binding does not declare is never offered to the model. That is
how `get_page_history` is handled against `mcp-atlassian`: that server returns one
named revision rather than a list of revisions, so the capability is absent from
its binding and the model never sees a tool it could select and no server could
honour.

**A binding never contains a credential.** The `env:` block names the variable a
value comes from; the value is read from the ambient environment when the server
process starts, and reaches that process alone. A binding is a committed file,
and a credential in it would be a credential in version control.

```yaml
env:
  CONFLUENCE_API_TOKEN: CONFLUENCE_API_TOKEN   # name -> source variable
```

A variable the binding asks for and the environment does not hold is refused
before the server starts, rather than producing an authentication failure several
calls later.

### `.env` — which server, and the secrets

```bash
WIKI_AGENT_MODE=mcp
WIKI_MCP_SERVER=mcp-atlassian     # config/mcp/mcp-atlassian.yaml
WIKI_MCP_ACCOUNT_ID=you@example.com

CONFLUENCE_URL=https://your-site.atlassian.net/wiki
CONFLUENCE_USERNAME=you@example.com
CONFLUENCE_API_TOKEN=...
```

`.env` is excluded by `.gitignore`. Never commit it.

## Setting up Confluence Cloud

1. Create an API token at
   <https://id.atlassian.com/manage-profile/security/api-tokens>.
2. Put the three `CONFLUENCE_*` values in `.env`.
3. Make sure Docker is running — the binding starts the server as a container, so
   nothing of that server is vendored into this repository.
4. Launch **Wiki Agent — Confluence** from VS Code.

Use the **API token, not Cloud OAuth**. Atlassian removed the v1 REST endpoints
from the `api.atlassian.com` gateway in August 2026 and that path now returns
`410 Gone`, which breaks the server's OAuth mode. The API token is unaffected —
and it is also the closest thing to the Data Center personal access token, so the
two deployments stay similar.

## Moving to Data Center

Replace three variables with two, and edit the `env:` block of the binding to
name them:

```bash
# Cloud                                    # Data Center
CONFLUENCE_URL=https://x.atlassian.net/wiki   CONFLUENCE_URL=https://confluence.corp.example
CONFLUENCE_USERNAME=you@corp.example          CONFLUENCE_PERSONAL_TOKEN=...
CONFLUENCE_API_TOKEN=...                      # CONFLUENCE_SSL_VERIFY=false for an internal CA
```

No agent code, no skill, no domain model and no prompt changes. That property is
the reason this server was chosen over the official Atlassian one.

## The one thing to get right: identity

A wiki restricts pages and spaces per person, so **the MCP server must carry the
identity of the person asking, never a shared service account.** An agent running
as a service account would read pages the user cannot see and summarise them back
in perfect good faith.

`mcp-atlassian` takes no account argument: it resolves the caller from the
`Authorization` header. The server supports both identity models, and which one
you get depends on the transport.

### Over stdio — one identity

There is no per-request header, so a stdio deployment has one set of credentials
and acts as **exactly one person**.

That is what `WIKI_MCP_ACCOUNT_ID` is for. Name the person the credentials belong
to, and the dialect refuses to serve anybody else rather than returning that
person's view of the wiki under another name. It is not needed for `wiki-local`,
which carries the caller on every call and scopes each answer itself.

### Over streamable HTTP — on behalf of the user

This is the mode an enterprise deployment wants. The server reads an
`Authorization` header on **every request** and builds a per-user client from it.

Start the server once:

```bash
docker run --rm -p 9000:9000 \
  -e CONFLUENCE_URL=https://your-site.atlassian.net/wiki \
  -e CONFLUENCE_PERSONAL_TOKEN=unused \
  -e READ_ONLY_MODE=true \
  -e TOOLSETS=confluence_pages,confluence_comments \
  ghcr.io/sooperset/mcp-atlassian:0.23.1 \
  --transport streamable-http --host 0.0.0.0 --port 9000
```

Then point the agent at it:

```bash
WIKI_AGENT_MODE=mcp
WIKI_MCP_SERVER=mcp-atlassian-http
WIKI_MCP_AUTH_SCHEME=basic          # or token, for Data Center
WIKI_MCP_USER_ACCOUNT=you@example.com
WIKI_MCP_USER_SECRET=<api token>
```

Three header formats, matching what the server accepts:

| `WIKI_MCP_AUTH_SCHEME` | Header sent | Deployment |
|---|---|---|
| `basic` | `Basic <base64(email:api_token)>` | Confluence Cloud |
| `token` | `Token <personal access token>` | Confluence Data Center |
| `bearer` | `Bearer <oauth access token>` | either, with OAuth |

**`bearer` deserves a warning.** The server resolves it to OAuth when it has an
OAuth configuration, and *silently downgrades it to a Data Center PAT when it does
not*. A deployment that meant OAuth and forgot to configure it does not fail — it
quietly authenticates differently. Say `token` when a PAT is what you mean.

Two defaults worth keeping:

- an **unauthenticated request is answered with HTTP 401**, not with the
  operator's credentials. `ALLOW_GLOBAL_CRED_FALLBACK` turns that off; do not set
  it. The server fails closed, which is the right default and rare enough to be
  worth saying out loud.
- `/healthz` is unauthenticated and returns `{"status": "ok"}`, so a load
  balancer needs no credential.

`CONFLUENCE_PERSONAL_TOKEN=unused` above is a genuine placeholder, not a
credential. The server needs *a* configuration to pass its startup check — it
makes no network call with it — and replaces it wholesale for every per-user
request. It contributes only the base URL, the SSL settings and the proxy
settings. `ATLASSIAN_EXTERNAL_AUTH_ENABLE=true` avoids the placeholder entirely
and is the cleaner choice once the deployment is real.

### Where the proof of concept stops

The agent sends **one configured credential**, because there is one local user
and no identity provider in front of it. Serving several people means minting an
on-behalf-of token for the authenticated caller and supplying it per request.

That is a change to one class — `WikiUserCredentials` in
`agents/wiki/src/ai_agent_lab/wiki/mcp/authorization.py`. Nothing above the MCP
boundary notices: not the dialect, not the skills, not the agent. The seam is
there on purpose.

## Narrowing what the server exposes

```bash
WIKI_MCP_READ_ONLY=true
WIKI_MCP_TOOLSETS=confluence_pages,confluence_comments
```

That server exposes around 98 tools across Jira and Confluence. The agent needs
ten. Two independent limits apply, and both are worth having: the server refuses
to expose what it was not asked to, and the binding refuses to advertise what it
did not declare.

`WIKI_MCP_READ_ONLY` is the switch that decides whether this agent may write at
all, and it governs **both** halves. The value reaches the server process, which
drops from nineteen tools to nine and exposes no write tool whatsoever; and the
agent reads it through `read_only_variable` in the binding and withdraws its four
write capabilities. They can no longer disagree — which they could, and the
symptom was an approved edit failing because the tool did not exist.

Set it to `false` when writing is what the deployment is for. An unset or
misspelled value reads as read-only.

## Adding another wiki system

Notion, XWiki, SharePoint: three steps, none of which touches the domain, the
skills or the agent.

1. Write a class implementing `WikiTools`, translating that server's shapes into
   domain models. Fence every piece of third-party free text as `UntrustedText`.
2. Register it in `ai_agent_lab.wiki.mcp.dialects.WikiDialectRegistry`.
3. Deliver `config/mcp/<server>.yaml` declaring the transport, the dialect, the
   capabilities the server really has, and the name it gives to each tool.

A server that implements `wiki_mcp.protocol` needs none of step 1 or 2:
`dialect: native` and it works. That is an offer to server authors, never a
requirement — and the server this repository actually targets does not take it.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `the openai provider requires a model name` | `OPENAI_CHAT_MODEL` is not set in `.env` |
| `wiki MCP server 'x' needs environment variable(s) [...]` | the binding names a variable `.env` does not hold |
| `server 'x' declares capabilities [...] but names no tool for them` | a `capabilities` entry has no matching `tools` entry |
| `speaks the 'x' dialect, which is not implemented` | `dialect:` names something not in the registry; the message lists what is |
| `could not be reached: FileNotFoundError` | for `mcp-atlassian`, Docker is not running |
| The agent says documentation does not exist | check `WIKI_AGENT_USER_ID`: a refusal is reported as a refusal, but an empty *search* looks like absence |
| A write is refused although you approved it | the confirmation was collected for a different target; see the `ConfirmationKey` discussion in [wiki-agent.md](./wiki-agent.md#how-an-approval-travels) |
| `page 'x' is at version N, not the expected M` | somebody edited the page between the drafting turn and the publishing turn. Draft again from the current version; the refusal is what stops their work being lost |
| The agent says it cannot change anything | `WIKI_MCP_READ_ONLY=true`. That withdraws the four write capabilities on purpose, because the server exposes no write tool in that mode. Set it to `false` and restart |
