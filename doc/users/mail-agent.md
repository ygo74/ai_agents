# Use the Mail Agent

The Mail Agent finds, reads, summarizes, and classifies messages. It can also
draft replies and apply labels. It asks for confirmation before an operation
that changes the mailbox. Use mock mode first to try the workflow against the
delivered sample mailbox.

## Start with the sample mailbox

Install the Mail Agent environment from the repository root:

```powershell
py -3.12 -m scripts.install --env mail-agent --into .venvs\mail-agent
Copy-Item .env.example .env
```

Set the model provider variables in `.env`, then run:

```powershell
$env:MAIL_AGENT_MODE = "mock"
.\.venvs\mail-agent\Scripts\python.exe -m ai_agent_lab.mail.adapters.cli
```

Ask `anything from John?`. The agent searches the sample mailbox and summarizes
matching messages. The mock mailbox needs no Gmail credential; the configured
language model still needs its own provider credential.

## Choose an environment file per component

All Mail launch commands use `.env` in the current directory by default.
Pass `--env-file` to use a different file. Relative paths start from the current
directory; absolute paths and paths containing spaces also work. An explicitly
selected file must exist. Process environment variables still take precedence.
The selected file replaces `.env`: missing values are not read from another file.

For a real mailbox, create private component files in the repository root:

- `.env.mail-agent`: model settings, `MAIL_AGENT_MODE=mcp`, inbound HTTP OIDC settings,
  and secret values referenced by the shared runtime's MCP configuration.
- `.env.gmail-mcp`: Google OAuth settings for the MCP server. The server uses JWT
  validation with `MAIL_MCP_AUTH_MODE=jwt`, the Keycloak realm issuer, and the
  `mail-mcp` audience. Never put Google credentials in the agent's environment.

The shared runtime must implement generic OAuth token exchange before this flow
can run. See the [runtime prerequisite](#runtime-prerequisite) below.
The agent's confidential Keycloak client must be allowed to exchange the verified
LibreChat access token for a token with audience `mail-mcp`. Keycloak and the MCP
server must accept that exchange and validate the resulting token. Do not give the
agent a Google credential or send the incoming LibreChat token directly to MCP.

Run from the repository root, using your installed Mail environment:

```powershell
.\.venvs\mail-agent\Scripts\python.exe -m mail_mcp.gmail.authorise `
  --env-file .env.gmail-mcp
.\.venvs\mail-agent\Scripts\python.exe -m mail_mcp.gmail.server `
  --env-file .env.gmail-mcp --transport streamable-http `
  --host 127.0.0.1 --port 9100 --owner "<test-user-Keycloak-sub>"
```

Keep the MCP server running. For authenticated OBO calls, start the HTTP host:

```powershell
.\.venvs\mail-agent\Scripts\python.exe -m ai_agent_lab.mail.adapters.http.server `
  --env-file .env.mail-agent --port 8123 --reload
```

The console host has no incoming HTTP identity and cannot perform this OBO flow;
use mock mode for the console, or provide a separate non-OBO server configuration.
The HTTP host serves the authenticated API on port 8123. HTTP reloads keep the
selected file. If startup reports a missing file, correct its path before retrying.
Discovery and agent authorisation utilities also accept `--env-file`.
VS Code Mail debug profiles ask for the file path at launch, with `.env` as the
initial choice. Agent and Gmail MCP profiles have separate prompts. The debug
profile's explicit `env` values, such as mock mode, still override the file.

## Try a confirmed operation

Ask the agent to apply a label to a message. It returns a confirmation request
with the message, sender, and label. Reply with the exact `CONFIRM cfm-...`
command to apply it, or `CANCEL cfm-...` to decline. In HTTP mode, keep the same
conversation ID when answering the ticket.

## Connect the authenticated caller to Gmail through MCP

### Runtime prerequisite

Token exchange belongs to `ai-enterprise-agent-runtime`. Mail contains no
Keycloak exchange implementation and no `MAIL_AGENT_MCP_OBO_*` settings.

The runtime checkout currently linked to the Mail environment (commit `abb70a7`)
only accepts `audience` and `scopes` in `McpDelegatedOAuthInput`. It requires an
injected `OAuthOnBehalfOfTokenSource`; without one, calls fail with
`delegated token exchange is not configured`. Its published configuration guide
also describes that injected port. This is not yet generic YAML-configured exchange.
The steps below prepare Keycloak, but the complete agent flow is **blocked** until
the runtime containing built-in exchange is available and its exact YAML schema
is used. Do not add guessed `token_url`, `client_id`, or `client_secret` fields:
the currently linked loader rejects unknown fields.

The valid resource part of `config/mcp/gmail-http.yaml` is:

```yaml
authentication_mode: oauth_on_behalf_of
authentication_oauth_on_behalf_of:
  audience: mail-mcp
  scopes: []
```

When the updated runtime is available, configure its generic exchange settings
in this server description, using its documented field names. The required
operator values for this test are:

| Value | Test setting |
|---|---|
| Grant | RFC 8693 token exchange, not client credentials or an Entra-specific OBO grant |
| Token endpoint | `https://localhost:8443/realms/localhost_backends/protocol/openid-connect/token` |
| Requesting client | `mail-agent` |
| Client credential | A private environment secret referenced by the runtime YAML schema |
| Subject token | The access token verified by the Mail HTTP host for this request |
| Requested audience | `mail-mcp` |
| Requested scopes | None for this initial test; use configured Keycloak scopes only |
| TLS | Validate certificates; trust the local Keycloak CA in each component |

Keep the secret out of YAML literals, prompts, and logs. Do not use the
LibreChat client secret as the Mail Agent client credential.

### Configure Keycloak clients

Use three separate clients in realm `localhost_backends`. These instructions
target [Keycloak Standard Token Exchange V2](https://www.keycloak.org/securing-apps/token-exchange#_standard-token-exchange).
If your version does not offer **Standard token exchange**, follow the
version-specific legacy instructions instead; do not mix V1 permissions with V2.

1. Keep `librechat` as the login client. Its access token identifies the user.
   Do not replace that token with a service-account token.
2. Create an OpenID Connect client `mail-agent`, enable **Client authentication**,
   and enable **Standard token exchange** in its capability settings. Store its
   credential privately for the runtime exchange configuration. Service accounts,
   direct access grants, impersonation, and refresh-token exchange are not needed
   for this test.
3. Create the resource client `mail-mcp` in the same realm. Its client ID must
   equal the YAML audience and `MAIL_MCP_OIDC_AUDIENCE`. It does not need browser
   login, token exchange, or a client secret on the MCP server; the server validates
   JWT signatures using Keycloak's published keys.
4. Under `librechat`'s dedicated client scope, add an **Audience** mapper.
   Select `mail-agent` as **Included Client Audience** and enable **Add to access
   token**. The LibreChat access token must contain `mail-agent` in `aud`.
   This is required both by inbound Mail validation and by Keycloak V2, because
   the exchange requester must be an audience of the subject token.
5. Under `mail-agent`'s dedicated client scope, add another **Audience** mapper
   with **Included Client Audience** set to `mail-mcp` and **Add to access token**
   enabled. This makes the target audience available in the exchange client's
   effective default scope. In V2, `audience=mail-mcp` filters available audiences;
   it cannot add an audience not provided by the effective scopes/mappers.
6. Keep the user email claim available to Mail, as required by its authenticated
   principal. Sign out of LibreChat and sign in again after mapper changes so
   the new access token contains the updated claims.

The expected claims are:

| Token | `iss` | `sub` | `aud` includes |
|---|---|---|---|
| LibreChat access token | `https://localhost:8443/realms/localhost_backends` | Test user's ID | `mail-agent` |
| Exchanged access token | Same issuer | Same test user's ID | `mail-mcp` |

`azp` may change from `librechat` to `mail-agent`; it identifies the client, not
the user. For this test, preservation of `sub`, not preservation of `azp`, is the
identity check.

### Configure the two services

This setup assumes LibreChat sends a Keycloak **access token** to the Mail Agent
HTTP API in `Authorization: Bearer <access-token>`. The Mail HTTP host validates
its issuer and audience before accepting the request. For the provided local
Keycloak realm, configure the agent environment with the exact issuer URL and an
audience that is present in the incoming access token (commonly `mail-agent` after
adding that audience to the Keycloak token mapper):

```dotenv
MAIL_AGENT_HTTP_OIDC_ISSUER=https://localhost:8443/realms/localhost_backends
MAIL_AGENT_HTTP_OIDC_AUDIENCE=mail-agent
MAIL_AGENT_MODE=mcp
```

Configure the server's private `.env_mcp_server` separately:

```dotenv
MAIL_MCP_AUTH_MODE=jwt
MAIL_MCP_OIDC_ISSUER=https://localhost:8443/realms/localhost_backends
MAIL_MCP_OIDC_AUDIENCE=mail-mcp
MAIL_MCP_RESOURCE_URL=http://127.0.0.1:9100/mcp
```

The issuer must equal the token's `iss` exactly. Do not replace it with
`https://keycloak:8443/...` just because a container resolves that hostname.
Arrange networking so each verifier can reach the canonical issuer or its
supported JWKS override while retaining the canonical issuer validation.
For LibreChat in Docker, the Mail API URL can use `host.docker.internal:8123`;
the agent-to-MCP URL remains `http://127.0.0.1:9100/mcp` when both run on the host.
Loopback HTTP is a local test setup only; protect bearer-token traffic with HTTPS
or an equivalent protected transport outside the host.

On the Google/MCP server side, complete Google OAuth consent and configure the
`GMAIL_OAUTH_*` variables. Keep its token file and Google credentials on the MCP
server only.

For a real mailbox request, the server's `--owner` must equal the test user's
Keycloak `sub`, not `local-user` or the email address. Mail sends
`principal.subject` as the MCP mailbox owner, and `SingleMailbox` refuses any
other owner. Run from the repository root:

```powershell
$testUserSubject = "<test-user-Keycloak-sub>"
.\.venvs\mail-agent-maf\Scripts\python.exe -m mail_mcp.gmail.server `
  --env-file .env_mcp_server --transport streamable-http `
  --host 127.0.0.1 --port 9100 --owner $testUserSubject
```

The VS Code **Mail MCP Gmail - HTTP** profile also asks for the mailbox owner;
use that same `sub`. This serves one preselected Google mailbox, not a per-user
Google credential directory.

### Test Keycloak exchange independently

Before testing the agent, validate Keycloak directly. Put a freshly issued
LibreChat access token and the private `mail-agent` client secret into the
current process environment, without saving them in scripts or shell history.
Run in PowerShell:

```powershell
$form = @{
  grant_type = "urn:ietf:params:oauth:grant-type:token-exchange"
  client_id = "mail-agent"
  client_secret = $env:MAIL_AGENT_EXCHANGE_CLIENT_SECRET
  subject_token = $env:LIBRECHAT_OPENID_ACCESS_TOKEN
  subject_token_type = "urn:ietf:params:oauth:token-type:access_token"
  requested_token_type = "urn:ietf:params:oauth:token-type:access_token"
  audience = "mail-mcp"
}
$exchange = Invoke-RestMethod -Method Post `
  -Uri https://localhost:8443/realms/localhost_backends/protocol/openid-connect/token `
  -ContentType "application/x-www-form-urlencoded" -Body $form
```

`MAIL_AGENT_EXCHANGE_CLIENT_SECRET` above is only a manual-test variable, not a
Mail Agent configuration option. Do not print `$form` or `$exchange`.
Inspect claims locally, never using an online JWT decoder. Confirm `sub` is
unchanged and `aud` contains `mail-mcp`. Decoding is a diagnostic check, not
signature verification; the MCP server must still verify signature, issuer,
audience, and expiry.

### Test the complete flow after upgrading the runtime

Start the HTTP agent with its own environment file as shown earlier. In
LibreChat's custom endpoint, send the logged-in user's access token as the
`Authorization` header using `Bearer {{LIBRECHAT_OPENID_ACCESS_TOKEN}}`.
The custom endpoint must target the host's Mail API, not the MCP server.
Then send a request to the Mail Agent HTTP API
using the access token already issued to LibreChat:

```powershell
$headers = @{ Authorization = "Bearer <LIBRECHAT_ACCESS_TOKEN>" }
$body = '{"model":"mail-agent","messages":[{"role":"user","content":"anything from John?"}]}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8123/v1/chat/completions `
  -Headers $headers -ContentType 'application/json' -Body $body
```

Once the generic runtime is configured, the Mail Agent validates the inbound access token,
then the runtime exchanges it with Keycloak
for a token intended for `mail-mcp`. The exchanged token, not the original LibreChat
token, authenticates the MCP request. An invalid, expired, or non-exchangeable token
fails the request; the agent does not fall back to unauthenticated access or a shared
secret. The answer summarizes messages in the connected mailbox.

Observe the verified principal at both boundaries using local debugger views or
sanitized authentication/audit records. Check that the same user `sub` reaches
Mail and MCP and that the exchanged token has the MCP audience. A mail answer
alone is not proof of identity propagation. Never log the tokens themselves.

| Failure | Check |
|---|---|
| `delegated token exchange is not configured` | The linked runtime has only the exchange port, not the required generic implementation |
| Mail returns 401 | Incoming issuer, `mail-agent` audience, expiry, keys, and trusted TLS certificate |
| Exchange returns `invalid_client` | Requesting client ID, secret, and client authentication method |
| Exchange rejects the request | Standard exchange enabled, requester present in subject `aud`, target mapper/effective scopes, realm and client policies |
| MCP returns 401 | Exchanged token issuer, `mail-mcp` audience, expiry, keys, and certificate trust |
| Mailbox owner is not served | `--owner` must match the authenticated user's `sub` |

Also check that an expired/wrong-audience token is rejected, and that replaying
the original LibreChat token directly to MCP is rejected when it lacks
`mail-mcp` in `aud`. Never solve a failure by disabling JWT validation.

This authenticates the caller at the MCP boundary but does not yet provide per-user
Google accounts: the current Gmail MCP server uses one Google OAuth credential and
serves that one mailbox to authorized callers. The local CLI has no inbound HTTP
caller token, so this OBO configuration is for the authenticated HTTP host; CLI
MCP calls require a separately configured non-OBO server profile.
Use [Serving the Mail Agent over HTTP](../../docs/mail-agent-http.md) for an API
example. The complete list of tools, permissions, and confirmation behavior is
in [Mail Agent](../../docs/mail-agent.md). To connect a real mailbox, start with
[Mail MCP server options](../../docs/mail-mcp-servers.md).
