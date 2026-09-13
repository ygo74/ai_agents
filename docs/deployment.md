# Deployment

How to run the Mail Agent, the Wiki Agent and the Gmail MCP server as containers.

Three images are published to the GitHub Container Registry:

| Image | What it is | Port |
|---|---|---|
| `ghcr.io/ygo74/mail-agent` | The Mail Agent, OpenAI-compatible HTTP surface | 8123 |
| `ghcr.io/ygo74/wiki-agent` | The Wiki Agent, same surface | 8124 |
| `ghcr.io/ygo74/mail-mcp-gmail` | Our mail MCP server, backed by the Gmail API | 9100 |

They are built by [`.github/workflows/images.yml`](../.github/workflows/images.yml)
for `linux/amd64` and `linux/arm64`, after the quality gates have passed. Each
carries an SBOM and a provenance attestation, and is scanned by Trivy on every
build.

---

## Security posture, port by port

This is the part to read before anything else, because the three ports are not
equally dangerous.

| Service | Who may reach it | What happens without a credential |
|---|---|---|
| `mail-agent` | An API key, or a bearer token from your identity provider | **Refuses to start.** Neither configured means no way to tell callers apart |
| `wiki-agent` | Same, with its own key and its own audience | **Refuses to start**, same rule |
| `mail-mcp-gmail` | A shared secret, a token from your IDP, or — if you say so — everyone | **Refuses to start over HTTP.** Over stdio no credential is needed |

### The three modes of an MCP server

`MAIL_MCP_AUTH_MODE` (and `WIKI_MCP_AUTH_MODE` for the wiki server) picks how a
caller is identified:

| Mode | What it checks | When to use it |
|---|---|---|
| `api_key` | A shared secret, as `Authorization: Bearer <secret>` | Two containers deployed together. The secret says "you are the agent I was deployed with", nothing about whose mailbox is read |
| `jwt` | A token from an OIDC issuer, against its published keys | A real identity provider. The server then publishes OAuth 2.1 metadata, so any MCP client discovers the issuer from the URL alone |
| `none` | Nothing | A server over public, read-only data — and only when somebody decided that |

The mode may be left unset when a token or an issuer is configured: that is an
unambiguous statement and existing deployments keep working. **It can never be left
unset to mean `none`.** A forgotten variable stops the process instead of opening a
port, because the alternative is a mailbox on an open port with nothing in the log
to say so.

In `jwt` mode the server also needs `MAIL_MCP_RESOURCE_URL` — the URL it calls
itself by, which is the audience a token must carry. A resource server that cannot
name itself cannot be discovered, so it refuses to start without one.

`mail-mcp-gmail` deserves a sentence of its own. **That process holds a Google
refresh token for a real mailbox.** Over stdio its security came from the process
boundary: the agent spawned it, and nothing else could speak to it. Over HTTP the
boundary is a network, and anything that can reach the port can read the mailbox.
The shared secret is what replaces the process boundary — not a convenience.

Consequently:

- Never publish port 9100 outside the deployment network. It belongs on an
  internal network with the agent, not behind an ingress.
- Rotate the secret the way you would rotate a mailbox password, because that is
  what it protects.
- The refusal to start is deliberate. A deployment that forgot the token used to
  be indistinguishable from one that had it; now it stops.

The two agents hold **no** mail or wiki credential. That is the whole reason for
three containers rather than one.

---

## Before the first run: the Gmail token

`mail-mcp-gmail` cannot obtain its own Google consent. The initial
authorisation opens a browser and listens on the loopback interface, and a
container can do neither.

Run it once on a workstation:

```powershell
$env:GMAIL_OAUTH_CLIENT_ID = "…apps.googleusercontent.com"
$env:GMAIL_OAUTH_CLIENT_SECRET = "…"
.\.venvs\dev\Scripts\mail-mcp-gmail-authorise.exe
```

This writes a token file. Mount it into the container read-only and point
`GMAIL_OAUTH_TOKEN_FILE` at the mount. See
[mail-mcp-servers.md](mail-mcp-servers.md) for the Google Cloud side: which
project, which scopes, and why `gmail.modify` is needed for the label operations.

The token file is a credential. It belongs in a secret store or a mounted volume
— never in an image, never in a repository, never in an environment variable
dump.

---

## Trying it without any credential

Both agents run against a deterministic dataset bundled in the image. This is the
right first run: it exercises the HTTP surface, the confirmation flow and the
security gates with no mailbox and no wiki behind them.

```powershell
docker run --rm -p 8123:8123 `
  -e MAIL_AGENT_MODE=mock `
  -e MAIL_AGENT_HTTP_API_KEY=choose-a-key `
  -e OPENAI_API_KEY=$env:OPENAI_API_KEY `
  -e OPENAI_CHAT_MODEL=gpt-4o-mini `
  ghcr.io/ygo74/mail-agent:latest
```

`MAIL_AGENT_MODE=mock` replaces the *mailbox*, not the model: the agent still
needs a chat model to reason with. Then:

```powershell
curl -Method POST http://127.0.0.1:8123/v1/chat/completions `
  -Headers @{ "x-api-key" = "choose-a-key"; "Content-Type" = "application/json" } `
  -Body '{"model":"mail-agent","messages":[{"role":"user","content":"anything from John?"}]}'
```

Without the header the same call answers `401`. That is the gate working.

---

## The full deployment

Three containers on one internal network. The agents are reachable from outside;
the MCP server is not.

```yaml
# compose.yaml
name: ai-agents

services:
  mail-mcp-gmail:
    image: ghcr.io/ygo74/mail-mcp-gmail:latest
    command: ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9100"]
    environment:
      # The secret that replaces the process boundary. Same value as the agent's
      # MAIL_MCP_HTTP_TOKEN below. No MAIL_MCP_AUTH_MODE is needed: a configured
      # token is an unambiguous statement. Set it to `jwt` or `none` to say
      # something else.
      MAIL_MCP_HTTP_TOKEN: ${MAIL_MCP_HTTP_TOKEN:?set a shared secret}
      GMAIL_OAUTH_CLIENT_ID: ${GMAIL_OAUTH_CLIENT_ID:?}
      GMAIL_OAUTH_CLIENT_SECRET: ${GMAIL_OAUTH_CLIENT_SECRET:?}
      GMAIL_OAUTH_TOKEN_FILE: /secrets/gmail-token.json
    volumes:
      - ${GMAIL_TOKEN_FILE:?path to the token produced by mail-mcp-gmail-authorise}:/secrets/gmail-token.json:ro
    networks: [internal]
    # No `ports`. Deliberately. This service is reachable from the agent and from
    # nothing else.

  # Not ours. The Confluence server is sooperset/mcp-atlassian, taken as
  # published. Over HTTP it acts on behalf of whoever the request names, which is
  # what lets the Wiki Agent respect per-person page restrictions.
  mcp-atlassian:
    image: ghcr.io/sooperset/mcp-atlassian:0.23.1
    command: ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000"]
    environment:
      CONFLUENCE_URL: ${CONFLUENCE_URL:?}
      ATLASSIAN_EXTERNAL_AUTH_ENABLE: "true"
      READ_ONLY_MODE: "true"
      TOOLSETS: confluence_pages,confluence_comments
      # Do not set ALLOW_GLOBAL_CRED_FALLBACK. It answers an unauthenticated
      # request with the operator's own credentials instead of a 401.
    networks: [internal]

  mail-agent:
    image: ghcr.io/ygo74/mail-agent:latest
    depends_on:
      mail-mcp-gmail:
        condition: service_healthy
    environment:
      MAIL_AGENT_MODE: mcp
      MAIL_AGENT_HTTP_API_KEY: ${MAIL_AGENT_HTTP_API_KEY:?}
      # Which binding to use, and how to authenticate on it.
      MAIL_MCP_SERVER: gmail-http
      MAIL_MCP_AUTH_SCHEME: bearer
      MAIL_MCP_HTTP_TOKEN: ${MAIL_MCP_HTTP_TOKEN:?}
      OPENAI_API_KEY: ${OPENAI_API_KEY:?}
      OPENAI_CHAT_MODEL: ${OPENAI_CHAT_MODEL:-gpt-4o-mini}
    ports:
      - "8123:8123"
    networks: [internal, edge]

  wiki-agent:
    image: ghcr.io/ygo74/wiki-agent:latest
    environment:
      WIKI_AGENT_MODE: mcp
      WIKI_AGENT_HTTP_API_KEY: ${WIKI_AGENT_HTTP_API_KEY:?}
      # `mcp-atlassian-service`, not `mcp-atlassian-http`: the latter names
      # localhost, which inside a container means the agent itself.
      WIKI_MCP_SERVER: mcp-atlassian-service
      WIKI_MCP_READ_ONLY: "true"
      WIKI_MCP_AUTH_SCHEME: basic
      WIKI_MCP_USER_ACCOUNT: ${ATLASSIAN_ACCOUNT:?}
      WIKI_MCP_USER_SECRET: ${ATLASSIAN_API_TOKEN:?}
      OPENAI_API_KEY: ${OPENAI_API_KEY:?}
      OPENAI_CHAT_MODEL: ${OPENAI_CHAT_MODEL:-gpt-4o-mini}
    ports:
      - "8124:8124"
    networks: [internal, edge]

networks:
  # One network, and no `internal: true`. Both MCP servers must reach the
  # internet - Google and Atlassian are where their data is - so cutting egress
  # would break them. What keeps them private is the absence of a `ports` entry:
  # nothing outside the deployment can address them at all.
  #
  # On Kubernetes this is a NetworkPolicy rather than a network: allow ingress to
  # the MCP servers only from the agent pods, and allow their egress.
  internal: {}
  edge: {}
```

Copy the secrets into a `.env` next to the compose file, or supply them from your
orchestrator's secret store. None of them belongs in the compose file itself.

`WIKI_MCP_READ_ONLY` must match how the Atlassian container was started. It is
declared twice because the two processes are started independently and neither
can read the other's configuration; when they disagree, the agent proposes edits
the server refuses.

In read-only mode the four write capabilities are withdrawn from the tools the
model can reach, so it says plainly that it cannot change this wiki rather than
proposing an edit and failing. Discovery still *describes* them, because the
descriptor says what the agent is rather than what this deployment lets it do —
so do not read `/v1/models` as the list of what will actually run.

### Using an identity provider instead of an API key

The API key is a demonstration mode: one key, one caller, no notion of *who*.
For anything beyond a trial, configure an issuer instead:

```yaml
      MAIL_AGENT_HTTP_OIDC_ISSUER: https://keycloak.example.com/realms/agents
      MAIL_AGENT_HTTP_OIDC_AUDIENCE: mail-agent
      MAIL_AGENT_HTTP_ROLES_CLAIM_PATH: realm_access.roles
```

Once an issuer is configured the API key is ignored — two ways in is one too
many. The signing keys are discovered from the issuer; name
`MAIL_AGENT_HTTP_JWKS_URL` only if your provider does not publish discovery.

Permissions then come from the token's roles rather than from a default, which is
what makes multi-user deployment meaningful. See
[mail-agent-http.md](mail-agent-http.md) and [wiki-agent-http.md](wiki-agent-http.md).

---

## Overriding the delivered configuration

Every image bundles `config/` — the agent manifest, the skill packages and the
MCP bindings — so it runs as it stands. A deployment that binds a different
server mounts its own over the top:

```yaml
    volumes:
      - ./my-config:/app/config:ro
```

`AI_AGENT_LAB_CONFIG_DIR` points elsewhere if you prefer a different path.

---

## Health

All three images declare a health check. It probes an authenticated endpoint
**without a credential** and treats `200`, `401` and `403` alike: all three prove
a process is up and answering. See [`deploy/healthcheck.py`](../deploy/healthcheck.py)
for why a probe that carried a credential would be worse — it would put a secret
in the image and in every orchestrator that reads it.

`mail-mcp-gmail` also answers `GET /healthz` without authentication. That route
returns nothing but liveness; every route that touches the mailbox is
authenticated.

---

## What the images do not contain

- No `.env`, no token file, no API key. The `.dockerignore` excludes them, and
  nothing in the build copies them.
- No credential of any kind is baked in. Everything arrives through the
  environment or through a mounted volume.
- The agent images carry only one agentic framework each — Microsoft Agent
  Framework for mail, LangChain/LangGraph for wiki. Keeping them apart is what
  makes the framework comparison meaningful, and it keeps each image smaller.
- `mail-mcp-gmail` carries neither agent nor framework. It speaks MCP and Gmail,
  and that is all.

---

## Building the images yourself

```powershell
docker build -f deploy/mail-agent.Dockerfile     -t mail-agent:dev .
docker build -f deploy/wiki-agent.Dockerfile     -t wiki-agent:dev .
docker build -f deploy/mail-mcp-gmail.Dockerfile -t mail-mcp-gmail:dev .
```

The build context is the repository root in all three cases: each image installs
several of the ten local distributions, and they live in different directories.

---

## Related

- [mail-agent-http.md](mail-agent-http.md) — the Mail Agent's HTTP surface
- [wiki-agent-http.md](wiki-agent-http.md) — the Wiki Agent's HTTP surface
- [mail-mcp-servers.md](mail-mcp-servers.md) — the Gmail server, its scopes and its consent
- [configuration.md](configuration.md) — every setting, and where it is read
- [implementing-an-agent.md](implementing-an-agent.md) — adding a third agent
