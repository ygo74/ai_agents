# Corporate Credit Analyst over HTTP

The Credit agent can be called by LibreChat, an OpenAI SDK client, or another
HTTP client. Its host exposes `GET /v1/models`, `POST /v1/chat/completions` and
`POST /v1/responses`, with normal responses and native streaming. Routes,
authentication, discovery and conversation lifecycle come from the shared
runtime; issuer identification still uses the same read-only skill and
EdgarTools MCP connection as the CLI.

## Start the service

Install the `credit-agent` environment and configure EdgarTools and your model
as explained in the [Credit guide](credit-agent.md). The installer includes
the HTTP dependencies. For a custom package installation, install the Credit
distribution with its `[http]` extra.

Copy `config/agents/credit/.env.example` to `.env_credit_agent_http` and fill in
`CREDIT_AGENT_HTTP_API_KEY`, your model settings, and the server configuration.
Then, from the repository root:

```bash
.venvs/credit-agent/bin/credit-agent-http \
  --config config --env-file .env_credit_agent_http --port 8125
```

You can also launch it with
`python -m ai_agent_lab.credit.adapters.http.server` in that environment.
The default listener is `127.0.0.1:8125`. `--host` selects the interface,
`--reload` enables development reloads, and `--ssl-certfile` plus
`--ssl-keyfile` enable HTTPS. Supply both TLS files together. Explicit
environment files must exist; process variables take precedence over file
values, and the selection is preserved across reloads.

The delivered manifest uses an API key in `X-API-Key` and establishes the caller
as `local-analyst`. The service refuses to start if the key is missing. This
HTTP key is independent of the model API key and the SEC contact identity.

## Call it from a client

Set `CREDIT_AGENT_HTTP_API_KEY` in your client environment to the same service
key. Discover the model:

```bash
curl http://127.0.0.1:8125/v1/models \
  -H "X-API-Key: ${CREDIT_AGENT_HTTP_API_KEY}"
```

Request an identification:

```bash
curl http://127.0.0.1:8125/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${CREDIT_AGENT_HTTP_API_KEY}" \
  -H "X-Conversation-Id: issuer-review" \
  -d '{"model":"corporate-credit-analyst","messages":[{"role":"user","content":"Identify Apple by ticker AAPL and include SEC sources."}]}'
```

For Responses, send
`{"model":"corporate-credit-analyst","input":"Identify CIK 320193"}`
to `/v1/responses`. Set `"stream":true` for server-sent events on either route.
The HTTP surface is conversational and requires the configured model. The CLI
`--query ... --json` remains the model-free structured identification path.

An OpenAI Python client uses the service URL and its required header:

```python
import os
from openai import OpenAI

with OpenAI(
    base_url="http://127.0.0.1:8125/v1",
    api_key="unused",
    default_headers={"X-API-Key": os.environ["CREDIT_AGENT_HTTP_API_KEY"]},
) as client:
    reply = client.chat.completions.create(
        model="corporate-credit-analyst",
        messages=[{"role": "user", "content": "Identify AAPL with SEC sources."}],
        extra_headers={"X-Conversation-Id": "issuer-review"},
    )
    print(reply.choices[0].message.content)
```

For LibreChat, configure a custom OpenAI endpoint with this base URL, the
`corporate-credit-analyst` model and the `X-API-Key` header. Forward
`X-Conversation-Id` for each discussion; without it, the runtime uses the
`default` conversation for that caller.

## Identity and conversation lifetime

For multiple users, replace the API-key security section of
`config/agents/credit/agent.yaml` with JWT/OIDC configuration. For example:

```yaml
http:
  endpoints: [chat_completions, responses]
  security:
    mode: jwt
    jwt:
      audience: credit-agent
      issuer: https://identity.example.com/realms/analysts
      allowed_algorithms: [RS256]
      required_claims: [sub, exp, iss, aud]
```

Use the actual issuer and audience accepted by your deployment. The runtime
discovers signing keys from that issuer; an explicit `jwks_url` is also
supported. Clients send `Authorization: Bearer <access-token>` in JWT mode;
the API key is then not accepted. See the runtime's
[HTTP manifest reference](https://github.com/ygo74/ai-enterprise-agent-runtime/blob/main/doc/python/agent-manifest.md#http-keys).

All authenticated callers receive the read-only `credit:identify` permission.
The verified subject scopes the tools and conversation cache. Request fields
cannot change the caller or grant permissions, and no email claim is required.
The SEC contact remains server infrastructure configuration. This delivery
does not perform writes or issue approval tickets.

The runtime retains a bounded process-local conversation cache: defaults are
200 conversations and 30 idle minutes, configurable through
`CREDIT_AGENT_HTTP_MAX_CONVERSATIONS` and `CREDIT_AGENT_HTTP_IDLE_MINUTES`.
Expiry, eviction and service shutdown close the associated MCP resources.
History is lost on restart; use a single worker for this delivery, or session
affinity when operating multiple workers. Candidate selection is still
revalidated against a fresh SEC search. Coordinate the aggregate SEC request
rate when multiple conversations launch separate EdgarTools subprocesses, or
connect them to one already-running server as described in the Credit guide.
