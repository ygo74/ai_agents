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

**[docs/deployment.md](../docs/deployment.md) is the deployment guide** — the
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

Start the agent against the deterministic dataset - no mailbox, no credentials:

```powershell
$env:MAIL_AGENT_MODE = "mock"
$env:MAIL_AGENT_HTTP_API_KEY = "choose-a-key"
.\.venvs\mail-agent-maf\Scripts\python.exe -m uvicorn `
  "ai_agent_lab.mail.application.entrypoints.service:build_app" `
  --factory --host 0.0.0.0 --port 8123
```

Point LibreChat at it by copying `librechat.yaml` next to your deployment and
setting `MAIL_AGENT_HTTP_API_KEY` to the same value in the LibreChat
environment.

If LibreChat runs in Docker and the agent runs on the host, replace
`http://mail-agent:8123/v1` with `http://host.docker.internal:8123/v1`.

## Checking it before involving LibreChat

```powershell
curl -Method POST http://127.0.0.1:8123/v1/chat/completions `
  -Headers @{ "x-api-key" = "choose-a-key"; "Content-Type" = "application/json" } `
  -Body '{"model":"mail-agent","messages":[{"role":"user","content":"anything from John?"}]}'
```

A well-formed reply carries `choices[0].message.content`. If it carries
`output` instead, the installed `ygo74-agent-runtime` predates the OpenAI
response mapping and LibreChat will not be able to read it - see
[docs/mail-agent-http.md](../docs/mail-agent-http.md).

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
