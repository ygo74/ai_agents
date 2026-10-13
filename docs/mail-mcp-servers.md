# Mail MCP servers

The agent never talks to a mail system. It talks to a mail MCP server, and the
server owns the integration. This page says which servers are supported, what
each one can actually do, and how to plug in another.

## Choosing a server

`MAIL_AGENT_MODE` selects only the backend:

```bash
MAIL_AGENT_MODE=mock                 # deterministic dataset, no MCP at all
MAIL_AGENT_MODE=mcp
```

In MCP mode, every delivered Mail skill must declare `mcp_server` in its
`skill.yaml`. Mail selects **one shared server** from these references. Missing
or conflicting references fail configuration; there is no environment selector
or fallback. All delivered Mail skills currently reference `gmail-http`.

The runtime `McpServerConfigurationLoader` reads
`config/mcp/<server>.yaml` for transport, URL, authentication, headers,
`request_timeout_seconds`, and network settings. Mail keeps its tool binding
and dialect selection, not a second connection-settings implementation.
To use another binding, update all delivered Mail skill references together.

### Local HTTP setup

`config/mcp/gmail-http.yaml` connects to our Gmail API MCP server at the literal
URL `http://127.0.0.1:9100/mcp`. The delivered configuration uses OAuth on behalf
of the authenticated HTTP caller (`oauth_on_behalf_of`) and requests the audience
`mail-mcp`. It requires the Mail Agent HTTP host to authenticate the caller and
exchange that verified Keycloak token; a console call has no such caller token.
The currently linked runtime has only the OBO port, not built-in exchange.
End-to-end OBO needs the runtime version with generic YAML-configured exchange;
Mail does not supply a Keycloak-specific source.
See the [Mail Agent user guide](../doc/users/mail-agent.md#connect-the-authenticated-caller-to-gmail-through-mcp)
for the complete Keycloak exchange configuration.

For a local server process, create `.env.gmail-mcp` with the following MCP
resource settings, then add the server-side `GMAIL_OAUTH_*` settings described in
[Setting it up](#setting-it-up):

```dotenv
MAIL_MCP_AUTH_MODE=jwt
MAIL_MCP_OIDC_ISSUER=https://localhost:8443/realms/localhost_backends
MAIL_MCP_OIDC_AUDIENCE=mail-mcp
MAIL_MCP_RESOURCE_URL=http://127.0.0.1:9100/mcp
```

Start the server from the repository root, after completing Google consent:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m mail_mcp.gmail.server `
  --env-file .env.gmail-mcp --transport streamable-http `
  --host 127.0.0.1 --port 9100 --owner "<test-user-Keycloak-sub>"
```

Then start the Mail HTTP host with `MAIL_AGENT_MODE=mcp` and the agent's OBO
settings once the runtime prerequisite is met. Use the test user's Keycloak `sub`
as `--owner`, since the server refuses other mailbox identifiers.
The server validates the exchanged JWT, not the original LibreChat token.
For a container, make the canonical issuer reachable and trusted from the container
without changing its value relative to the token's `iss`. Advertise the reachable
resource URL. The loopback URL above is for local development.

The API-key authentication mode remains available for a deliberate single-caller
setup: configure `authentication_mode: api_key` in a private copy of the YAML and
use matching server/client secret values. It does not associate MCP calls with an
individual caller and is not the delivered OBO configuration.
## Servers

| | `mock` | `local` | `gmail-api` | `gmail-http` | `gmail` |
|---|---|---|---|---|---|
| Backed by | JSON dataset | JSON dataset | a real mailbox | a real mailbox | a real mailbox |
| Protocol | none | MCP over stdio | MCP over stdio | MCP over HTTP | MCP over HTTP |
| Server | — | ours | **ours** | **ours** | Google |
| Credentials | none | none | server-side Google OAuth | Keycloak JWT; server-side Google OAuth | client-side Google OAuth |
| Coverage | 12/12 | 12/12 | **12/12** | **12/12** | 10/12 |
| Usable today | yes | yes | **yes** | **yes; delivered default** | Workspace preview only |

The two the official Google server lacks are `send_mail` and `delete_label`. It
is not a defect on either side: it is what a binding is for. The agent, the
skills and the delivered skill packages are identical whichever server is bound,
and the two capabilities are simply never offered to the model against `gmail`.
`tests/integration/test_capability_exposure.py` holds that claim.

### `gmail-http` and `gmail-api` — our server, on the Gmail REST API

This is the one that works on a personal account.

There are two different Google services, and only one of them is generally
available:

| Service | State |
|---|---|
| `gmailmcp.googleapis.com` — the official MCP server | preview, requires enrolling the Cloud project in the Google Workspace Developer Preview Program, which a personal account cannot join |
| `gmail.googleapis.com` — the Gmail REST API | generally available |

So the integration sits behind **our own MCP server**, which speaks the contract
on one side and the Gmail REST API on the other:

```text
Agent -> Skills -> MCP tools -> our MCP server (HTTP or stdio) -> Gmail REST API
                                 the token lives here, and nowhere else
```

The agent is unchanged. It never sees a Google credential, and the MCP boundary
the whole architecture rests on is intact.

#### One trap worth knowing about

Gmail's `label:` search operator matches the **name** a person reads, while
every other label operation — applying, removing, deleting — takes an
**identifier**. Putting an identifier after `label:` is not an error: Gmail
matches nothing and reports an empty mailbox, so a broken filter looks exactly
like a mailbox with no such messages.

This server therefore passes labels as the `labelIds` request parameter, which
is identifier-based and exact. The official Google server accepts only a query
string, so its dialect resolves the identifiers to names first.
`tests/contract/test_mail_tools_contract.py` pins the behaviour on both.

#### When Google says "not now"

A mailbox search fans out into one request per message, so a single rate limit
or dropped connection would fail a search that was seconds from succeeding.
Reads are retried three times with a growing, slightly randomised delay — the
randomness matters, because requests that failed together would otherwise come
back in step and repeat the burst that rate-limited them.

Only `429` and `5xx`, plus transport failures, are retried. They all mean
nothing happened.

**Writes are never retried.** A request that timed out may still have been
applied, and sending it again could file a message twice or create a second
draft. Reporting a failure that did not happen is a nuisance; performing an
operation twice without being asked is a defect.

#### Setting it up

1. **Google Auth Platform > Data Access**, add the scopes:

   ```text
   https://www.googleapis.com/auth/gmail.readonly
   https://www.googleapis.com/auth/gmail.compose
   https://www.googleapis.com/auth/gmail.modify
   ```

   The first two cover reading and drafting; `gmail.modify` is what the four
   label operations need - read state, archiving, applying and removing labels.

2. **Clients > Create client**, type **Web application**, redirect URI:

   ```text
   http://localhost:8765/oauth/callback
   ```

3. Configure the **server's** environment:

   ```bash
   GMAIL_OAUTH_CLIENT_ID=<client id>
   GMAIL_OAUTH_CLIENT_SECRET=<client secret>
   ```

4. Consent once on a workstation:

   ```powershell
   .\.venvs\mail-agent-maf\Scripts\python.exe -m mail_mcp.gmail.authorise
   ```

   The command reports the scopes actually granted and reads the labels back, so
   a grant that cannot be used is reported now rather than mid-conversation.

5. Start the HTTP server, then the agent, as shown above. `GMAIL_OAUTH_*`
   credentials and the Google token file belong only to the Gmail server.
   The Mail Agent needs its inbound OIDC and shared-runtime token-exchange settings,
   not Google credentials. The delivered `gmail-http` binding uses OBO/JWT;
   API-key mode is an explicit alternative described above. `gmail-api` is the
   same server over stdio; to use it, change every delivered Mail skill's
   `mcp_server` to `gmail-api` and use a non-OBO profile.

The authorisation request carries `access_type=offline` and `prompt=consent`,
which is what makes Google issue a **refresh token**. Without both, the grant
dies within the hour - which is exactly what happens through the MCP OAuth flow.

#### Notes worth knowing

- **A query costs one request per hit.** Gmail answers a search with identifiers
  only. Those reads are issued concurrently and bounded to eight: sequentially, a
  default page of twenty exceeded the MCP deadline; concurrently it takes under
  three seconds.
- **`gmail.modify` is broad.** It covers everything except permanent deletion.
  There is no narrower scope for applying a label to a message. If the agent only
  ever needs to read and draft, drop it and the four label capabilities with it.

### `gmail` — the official Google server

There is **no official Gmail MCP server on GitHub**: it is a hosted service at
`https://gmailmcp.googleapis.com/mcp/v1`, documented at
[developers.google.com](https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server).

#### Setting it up

1. Enable the services in your Google Cloud project:

   ```bash
   gcloud services enable gmail.googleapis.com --project=PROJECT_ID
   gcloud services enable gmailmcp.googleapis.com --project=PROJECT_ID
   ```

2. **Google Auth Platform > Data Access**, add exactly these two scopes:

   ```text
   https://www.googleapis.com/auth/gmail.readonly
   https://www.googleapis.com/auth/gmail.compose
   ```

3. **Google Auth Platform > Clients > Create client**, type **Web application**,
   and register this authorised redirect URI:

   ```text
   http://localhost:8765/oauth/callback
   ```

   If the audience is **External**, add your own address under **Audience > Test
   users**, or consent will be refused.

4. Configure `authentication_oauth` in `config/mcp/gmail.yaml`. Replace its
   literal `client_id: configure-in-google-cloud` with the client ID issued by
   Google. Keep the secret as `${MAIL_MCP_OAUTH_CLIENT_SECRET}`, the callback
   port as `8765`, the scopes as `gmail.readonly` and `gmail.compose` (their full
   URLs above), and the token file as `.secrets/mail-mcp-token.json`.
   Put only the client secret in the environment:

   ```bash
   MAIL_MCP_OAUTH_CLIENT_SECRET=<client secret>
   ```

   The runtime connection excerpt is:

   ```yaml
   request_timeout_seconds: 600
   authentication_mode: oauth
   authentication_oauth:
     client_id: configure-in-google-cloud  # replace with your issued client ID
     client_secret: ${MAIL_MCP_OAUTH_CLIENT_SECRET}
     callback_port: 8765
     scopes:
       - https://www.googleapis.com/auth/gmail.readonly
       - https://www.googleapis.com/auth/gmail.compose
     token_file: .secrets/mail-mcp-token.json
   ```

   `.env` and `.secrets/` are both excluded by `.gitignore`. The secret is held
   as a `SecretStr`, so logging a settings object cannot reveal it, and the
   issued token is written to `.secrets/mail-mcp-token.json` with `0600`
   permissions.

#### Recording what the server exposes

Response shapes are not specified by MCP and Google does not publish theirs, so
they are asked for rather than assumed:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.adapters.cli.discover --server gmail
```

`--server gmail` loads the same runtime YAML connection configuration used by
Mail. The browser opens for consent once, the token is stored, and the tool schemas
are written to `data/mcp-discovery/gmail-tools.json`. That recording is what the
Gmail dialect is written against. The command only lists tools; it reads no
message.

#### Authorising, once

Consent happens in a browser and takes as long as a person takes, so it is not
done inside a tool call:

```powershell
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.adapters.cli.authorise --server gmail
```

The browser opens, you approve, the token is stored in
`.secrets/mail-mcp-token.json` with `0600` permissions, and the command reads
the labels back to prove the grant is usable.

`authorise` defaults to `gmail`, the official Google service, not our local
HTTP server. Both `authorise --server` and `discover --server` load the selected
runtime YAML, including OAuth configuration. Non-secret client parameters no
longer come from environment variables. These utility commands do not change
the server selected by the agent's skill manifests. Use
`mail_mcp.gmail.authorise` for consent to our own Gmail API server.

#### Scopes: what the server asks for, and what we grant

The published guide says to configure `gmail.readonly` and `gmail.compose`. The
live server asks for considerably more. Recorded from the real authorisation
request:

```text
https://mail.google.com/     full mailbox control, permanent deletion included
gmail.modify
gmail.readonly
gmail.labels
gmail.metadata
```

The MCP SDK does not merely suggest those: it **overwrites** the configured
scope with whatever the resource server advertises, and widens it again when a
call returns `insufficient_scope` (`mcp/client/auth/oauth2.py:565` and `:614`).

Mail delegates OAuth provider construction to the runtime's
`McpOAuthProviderFactory`, using the scopes declared in runtime YAML rather
than a Mail-specific OAuth provider. The runtime pins the requested scopes
before authorisation so the agent asks only for what it needs.
The recorded Google grant
carries `gmail.readonly gmail.compose` and nothing else. Widen it deliberately
in `authentication_oauth.scopes` in `config/mcp/gmail.yaml` if a capability
genuinely needs more - applying a label needs `gmail.modify`, which also has to
be added to the consent screen. The YAML sets `request_timeout_seconds: 600`
for browser consent. Mail does not support `delegatedOAuth`; configuring it
fails explicitly rather than silently using another authentication mode.

Granting `https://mail.google.com/` to an agent that reads mail and drafts
replies would mean a stolen token can erase the mailbox. That is not a
theoretical concern for a stored refresh token.

#### Preview enrolment

The server is not generally available. A call returns:

> Access to this tool requires that your Google Cloud project is enrolled in the
> Google Workspace Developer Preview Program.

Enrol at [developers.google.com/workspace/preview](https://developers.google.com/workspace/preview)
before the Gmail-backed agent can read anything.

#### What it does not do, and why that is visible in the agent

| Capability | Status |
|---|---|
| `send_mail` | **absent by design.** Google's model is that a draft is prepared and the person sends it from Gmail. |
| `delete_label` | **absent.** The server creates labels — `create_label` — but offers no deletion of any kind. |
| `search_mail` | present, but searches **threads** rather than messages. |
| `get_mail` | present as `get_message`, although the published guide omits it. Recorded from the live server. |

The binding declares only what the server can serve, and the agent offers the
model nothing else. Ask the Gmail-backed agent to send an email, or to delete a
label, and there is no tool to select — rather than a tool that fails halfway
through a conversation. `tests/integration/test_capability_exposure.py` pins
that, including the fact that the same agent *does* offer label deletion against
`gmail-api`.

Why not a community server? The two popular ones return **prose formatted for a
language model**: no message identifiers inside threads, no read state, no
labels, and message bodies inserted without a delimiter. Since a body is written
by whoever emailed you, parsing that prose is a parser-injection vector, and the
missing identifiers would break the grounding check that keeps an analysis
anchored to real messages. One of them is also archived and forces
`gmail.settings.basic`, which allows creating auto-forward filters.

### `local` — the reference server

`mail_mcp.reference.server` speaks our own tool names and
returns the payloads of `mail_mcp.protocol.payloads`. It is backed by the
same dataset as the mock mode, so it needs no network, no credentials and no
mailbox.

It exists for two reasons: it runs the real protocol stack in tests, and it is
the reference a new server can be written against.

```powershell
$env:MAIL_AGENT_MODE = "mcp"
.\.venvs\mail-agent-maf\Scripts\python.exe -m ai_agent_lab.mail.adapters.cli
```

Before this command, change every delivered Mail skill's `mcp_server` to
`local`. The reference binding spawns the stdio server; no separate HTTP server
or shared header secret is needed.

## Plugging in another server, such as one backed by EWS

Two paths, depending on what the server answers.

**If the server implements our contract** — our tool names, our payloads,
our error codes — there is nothing to write. Deliver a binding:

```yaml
# config/mcp/ews.yaml
server: ews
transport: stdio          # or http, with a url
command: python
args: [-m, my_company.ews_mcp_server]
dialect: native

capabilities:             # anything absent is never offered to the model
  - search_mail
  - get_mail
  - get_thread
  - list_labels
  - create_draft
  - send_mail
  - mark_read
  - archive_mail
  - apply_label
  - remove_label

tools:                    # a native server names its tools like we do
  search_mail: search_mail
  get_mail: get_mail
  # ...
```

Set all delivered Mail skills' `mcp_server` to `ews`, then prove it with the
suite that already exists:

```python
class TestEwsContract(MailToolsContractTests):
    @pytest.fixture
    def mail_tools(self, ...):
        return McpMailTools(connection, binding, owner_id="...")
```

**If the server has its own shapes**, declare a different `dialect` and write
one client implementing `MailTools`. That is the Gmail case, and the only place
a server's vocabulary is allowed to appear.

### The payload contract

`mail_mcp.protocol.payloads` is the wire format: validated models, plain
strings for free text, ISO-8601 timestamps. A client wraps free text as
untrusted content on the way in, so a server never has to think about it.

Failures carry a code so they keep their meaning across the protocol:

```text
mail_not_found: message 'm-42' was not found
mail_access_denied: access to 'mailbox of bob' was denied by the mail system
mail_unavailable: ...
mail_protocol: ...
```

A server that reports no code still fails loudly: its text is surfaced as a
protocol error rather than guessed at.

## Security

- **A client never asks for a mailbox it does not serve.** The configured owner
  is checked before the call, so cross-mailbox access does not depend on the
  server getting it right. The server remains the authority for everything else.
- **Everything a server returns is untrusted.** Subjects, bodies, display names
  and label names are fenced as `UntrustedText` at the boundary, whichever
  server produced them.
- **Prompt injection.** Google recommends Model Armor on top of the official
  server; our own fencing applies regardless.
- **Credentials never leave infrastructure.** No token reaches a prompt, a log
  or a `UserContext`.
