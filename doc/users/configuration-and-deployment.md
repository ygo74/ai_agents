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

## Select another agent manifest

Both Mail and Wiki support these process environment variables. They can also
be set in the environment file selected by the launcher. Process values take
precedence over that file.

| Variable | Default | Effect |
|---|---|---|
| `YGO74_AGENT_RUNTIME_CONFIG_DIR` | `config/` under the working directory | Base directory for all configuration. |
| `AGENT_CONFIG_SUBDIR` | `wiki` for Wiki; `mail` for Mail | Selects both `agents/<subdir>/` and `skills/<subdir>/`. |
| `AGENT_MANIFEST_FILENAME` | `agent.yaml` | Selects the YAML file inside `agents/<subdir>/`. |

Missing, empty, or whitespace-only selectors use their defaults. Values are read
when the manifest is loaded, not when Python imports the module. The two
selectors are independent and apply to the process, not to individual requests.

To change only a Wiki manifest without copying instructions, skills, or MCP
configuration, run from the repository root with the Wiki environment installed
and provider settings configured as above:

```powershell
Copy-Item config\agents\wiki\agent.yaml config\agents\wiki\agent.local.yaml
# Edit agent.local.yaml before starting the agent.
$env:AGENT_CONFIG_SUBDIR = "wiki"
$env:AGENT_MANIFEST_FILENAME = "agent.local.yaml"
.\.venvs\wiki-agent\Scripts\wiki-agent.exe
```

The launcher loads `config/agents/wiki/agent.local.yaml` and still uses
`config/agents/wiki/AGENT.md`, `config/skills/wiki/`, and `config/mcp/`.
The same selection applies to CLI and HTTP composition. A missing or invalid
selected manifest raises a configuration error; it never falls back silently.

For Mail, place the alternative YAML under `config/agents/mail/`, set
`AGENT_CONFIG_SUBDIR=mail`, and start the Mail launcher. To duplicate a complete
Wiki configuration, copy `config/agents/wiki/` to `config/agents/wiki-local/`
and `config/skills/wiki/` to `config/skills/wiki-local/`, then set
`AGENT_CONFIG_SUBDIR=wiki-local`. Shared MCP files remain under the same
`config/mcp/`; the configuration root does not need to be duplicated.

The manifest filename option is implemented in the shared Python runtime. When
using published runtime packages instead of an editable checkout, install a
runtime release containing `AGENT_MANIFEST_FILENAME` support.

## Choose the MCP backend

Mail and Wiki both use the same rule: a skill's `mcp_server` overrides the
agent manifest's default. A skill with MCP tools can omit `mcp_server` when the
agent declares it. Skills without MCP tools do not select a backend.

For example, to run Mail through the delivered `gmail-api` binding, set this in
your selected agent manifest:

```yaml
mcp_server: gmail-api
```

Keep each Mail skill's `mcp_tools` list, but omit its `mcp_server` to inherit
`gmail-api`. No change to the skills is needed when you switch the agent default
later. To explicitly override that default, declare the server in the relevant
skill manifest:

```yaml
mcp_server: gmail-http
mcp_tools:
  - get_mail
```

Both agents use a runtime MCP registry. It creates **one connection per
referenced server**, shared by skills selecting that server. In the example,
`get_mail` uses `gmail-http`; other skills still inherit `gmail-api`. Prepare
both servers and their authentication before running the agent. This example
shows routing, not data replication: identifiers returned by one server must
be meaningful to the server used by a later skill.

Reasoning skills use their own selected server for all declared MCP calls.
An override on `get_mail` does not change the server of `summarise_mail`; set an
override on that skill too when needed. Each skill is restricted to its declared
`mcp_tools`. Missing server declarations or missing remote tools produce an
explicit configuration or tool error, without silently selecting another server.
Wiki follows the same selection rule, and still applies read-only restrictions.

The delivered agents normally use one server. Keeping the default in the agent
manifest is sufficient; no extra server configuration is required unless a skill
selects another server.

Each selected name must have a matching `config/mcp/<server>.yaml` binding that
supports the agent's tools. Server authentication stays in that binding and
its referenced environment variables, not in the agent or skill manifests.

## Keep Wiki credentials bound to their owner

For a Wiki MCP binding without explicit runtime authentication, legacy
`WIKI_MCP_AUTH_SCHEME` headers use `WIKI_MCP_USER_ACCOUNT` and
`WIKI_MCP_USER_SECRET`. These fixed credentials belong to
`WIKI_AGENT_USER_ID`, not to whichever subject sends an HTTP request.
Set that owner to the same subject as the local API-key identity. A different
subject is denied before MCP access; changing to JWT does not turn a shared
secret into per-user credentials.

Multi-user hosting needs a caller-bound credential source injected into
`WikiAgentCompositionRoot(credentials=...)`. The existing `WikiUserCredentials`
contract must resolve credentials for the authenticated user or raise
`WikiAccessDeniedError`. A missing user credential never falls back to the fixed
configuration secret. Keep this source in the trusted composition layer, never
in prompts or retrieved content.

Explicit MCP YAML authentication remains owned by the shared runtime. It does
not read legacy Wiki credentials. Keep the upstream account guard configured
with `WIKI_MCP_ACCOUNT_ID` when that authentication uses a single shared account.

See the [credential ownership regression tests](../../tests/security/test_wiki_credential_ownership.py)
for fixed-owner and injected-source examples.

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
