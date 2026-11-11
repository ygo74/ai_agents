# Deployment assets

Everything needed to run an agent of this laboratory — as a container behind an
orchestrator, or on a workstation behind a chat interface.

## What is here

| File | Purpose |
|---|---|
| `mail-agent.Dockerfile` | The Mail Agent, HTTP, port 8123. |
| `wiki-agent.Dockerfile` | The Wiki Agent, HTTP, port 8124. |
| `mail-mcp-gmail.Dockerfile` | Our mail MCP server on the Gmail API, port 9100. |
| `healthcheck.py` | The probe all three images use, and why it carries no credential. |
| `librechat.yaml` | Declares the Mail Agent as a custom OpenAI-compatible endpoint. |

The images are built and published by
[`.github/workflows/images.yml`](../.github/workflows/images.yml) to
`ghcr.io/ygo74/{mail-agent,wiki-agent,mail-mcp-gmail}`, for `linux/amd64` and
`linux/arm64`, after the quality gates have passed. Each carries an SBOM and a
provenance attestation and is scanned by Trivy.

**[Deployment guide](../doc/users/deployment.md)** covers the
compose file, the Gmail token prerequisite, and the security posture of each
port. What follows here is the workstation path.

## Building locally

```powershell
docker build -f deploy/mail-agent.Dockerfile     -t mail-agent:dev .
docker build -f deploy/wiki-agent.Dockerfile     -t wiki-agent:dev .
docker build -f deploy/mail-mcp-gmail.Dockerfile -t mail-mcp-gmail:dev .
```

The build context is the repository root in all three cases: each image installs
several of the ten local distributions, and they live in different directories.

## Running the Mail Agent for LibreChat

Start the agent against the deterministic dataset. The checked-in Mail manifest
uses JWT/OIDC; the API-key commands below assume you selected API-key mode in
`config/agents/mail/agent.yaml`. JWT deployments set
`MAIL_AGENT_HTTP_MCP_RESOURCE_URL` to their public HTTPS URL ending in `/mcp`
and send a bearer token from the configured issuer.

```powershell
$env:MAIL_AGENT_MODE = "mock"
$env:MAIL_AGENT_HTTP_API_KEY = "choose-a-key"
.\.venvs\mail-agent-maf\Scripts\python.exe -m uvicorn `
  "ai_agent_lab.mail.bootstrap.service:build_app" `
  --factory --host 0.0.0.0 --port 8123
```

Point LibreChat at it by copying `librechat.yaml` next to your deployment and
setting `MAIL_AGENT_HTTP_API_KEY` to the same value in the LibreChat
environment.

If LibreChat runs in Docker and the agent runs on the host, replace
`http://mail-agent:8123/v1` with `http://host.docker.internal:8123/v1`.

To run the Python launcher with direct HTTPS, pass both certificate paths:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.adapters.http.server `
  --host 0.0.0.0 --port 8123 `
  --ssl-certfile C:\secrets\mail-fullchain.pem `
  --ssl-keyfile C:\secrets\mail-private-key.pem
```

The key file stays outside the repository. For a container deployment, mount
the files read-only and pass Uvicorn's `--ssl-certfile` and `--ssl-keyfile`
options in the container command; see the [direct HTTPS deployment example](../doc/users/deployment.md#serving-an-agent-directly-over-https).

The same Mail process exposes MCP Streamable HTTP at `/mcp` and the single `invoke_agent` tool. It uses the same authentication policy and conversation cache as the OpenAI routes. The Wiki process exposes the same MCP path with its API-key policy; its identity can be a subject without an email claim. The cache is process-local, so deployments with multiple workers or replicas need session affinity. See the [Mail HTTP guide](../doc/users/mail-agent-http.md), [Wiki HTTP guide](../doc/users/wiki-agent-http.md), and [MCP hosting specification](../spec/integrations/mcp-server-hosting.md).

## Checking it before involving LibreChat

```powershell
curl -Method POST http://127.0.0.1:8123/v1/chat/completions `
  -Headers @{ "x-api-key" = "choose-a-key"; "Content-Type" = "application/json" } `
  -Body '{"model":"mail-agent","messages":[{"role":"user","content":"anything from John?"}]}'
```

A well-formed reply carries `choices[0].message.content`. If it carries
`output` instead, the installed `ygo74-agent-runtime` predates the OpenAI
response mapping and LibreChat will not be able to read it - see
[Mail Agent HTTP guide](../doc/users/mail-agent-http.md).

## Confirmations

Operations that change the mailbox are not performed during the turn that
proposes them. The agent answers with a ticket:

```text
Awaiting your confirmation - nothing has been changed yet:

- **Apply this label to the message?**
  - Message: m-alpha-1
  - Subject: Project Alpha - architecture review
  - From: john.smith@example.com
  - Label: Finance (FINANCE)
  - Reply `CONFIRM cfm-1a2b3c4d5e6f` to approve, `CANCEL cfm-1a2b3c4d5e6f` to decline.
```

Each entry names the message rather than only its identifier, because the answer
may come several messages later and nobody should have to scroll back to find out
what they are approving.

Replying `CONFIRM cfm-…` performs exactly the stored operation; `CANCEL cfm-…`
discards it. Both consume the ticket. This is deliberate, not a limitation of
the transport: a chat API has no side channel to hold a turn open on, and a
model must never be the authority on whether a side effect happens.

## Still to come

- Keycloak realm and compose file for the multi-user mode. The endpoint block is
  already written in `librechat.yaml`, commented out.
- A2A surface, for the aggregator agent to call this one.
