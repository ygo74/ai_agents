# Configure and deploy the agents

Agent instructions, capability descriptions, MCP bindings, and security
defaults are delivered under `config/`. Provider credentials and runtime
choices belong in the process environment or a secret store.

## Change local configuration

From the repository root, install a Wiki Agent environment and set its runtime
mode:

```powershell
py -3.12 -m scripts.install --env wiki-agent --into .venvs\wiki-agent
$env:WIKI_AGENT_MODE = "mock"
$env:OPENAI_API_KEY = "<your key>"
$env:OPENAI_CHAT_MODEL = "gpt-4o-mini"
.\.venvs\wiki-agent\Scripts\wiki-agent.exe
```

The agent starts against the sample wiki. If configuration is invalid or a
capability is not available from the selected MCP binding, the agent refuses or
omits that capability instead of asking a nonexistent server tool to run.

Use [Configuration](../../docs/configuration.md) to edit manifests and prompts.
Keep secrets out of `agent.yaml`, `skill.yaml`, and committed `.env.example`
files.

## Run the HTTP service locally

For a local API-key-protected Wiki Agent, configure mock mode and start Uvicorn:

```powershell
$env:WIKI_AGENT_MODE = "mock"
$env:WIKI_AGENT_HTTP_API_KEY = "<local-demo-key>"
.\.venvs\wiki-agent\Scripts\python.exe -m uvicorn `
  "ai_agent_lab.wiki.bootstrap.service:build_app" --factory --port 8124
```

Send a request in another terminal:

```powershell
curl -Method POST http://127.0.0.1:8124/v1/chat/completions `
  -Headers @{"x-api-key" = "<local-demo-key>"; "Content-Type" = "application/json"} `
  -Body '{"model":"wiki-agent","messages":[{"role":"user","content":"What is in scope for Apollo?"}]}'
```

The checked-in `config/agents/wiki/agent.yaml` references this environment key
and maps it to a local subject. The service returns an OpenAI-compatible answer
and rejects requests without the key. For JWT/OIDC, change that manifest to
`http.security.mode: jwt` and put the issuer/audience there. See the
[manifest guide](../../docs/configuration.md#fixed-manifest-schemas) and the
[HTTP serving guide](../../docs/wiki-agent-http.md).

## Deploy containers

The repository publishes separate agent and MCP server images. Keep the
credential-holding MCP service on a private network and expose only the agent
port required by clients. The deployment guide includes Compose examples,
health checks, OIDC settings, and server-side read-only controls: see
[Deployment](../../docs/deployment.md).
