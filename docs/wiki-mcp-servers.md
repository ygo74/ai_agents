# Wiki MCP servers

The agent never talks to Confluence. It talks to a wiki MCP server, and the
server owns the integration. This page says which servers are supported, what
each one can actually do, and — the reason this research was done at all — which
one survives the move from Confluence Cloud to Confluence Data Center without a
line of agent code changing.

## The constraint

The lab runs against **Confluence Cloud**. The target deployment is **Confluence
Data Center**. The two differ in authentication, in REST version and in half
their endpoints. None of that may reach above the MCP boundary.

## The answer

**`sooperset/mcp-atlassian`**, pinned to **v0.23.1 or later**. It is the only
mature server covering both deployments behind an **identical tool surface**.

The migration is a change of environment variables and nothing else:

```bash
# Cloud, today                                # Data Center, later
CONFLUENCE_URL=https://x.atlassian.net/wiki   CONFLUENCE_URL=https://confluence.corp.example
CONFLUENCE_USERNAME=you@corp.example          CONFLUENCE_PERSONAL_TOKEN=...
CONFLUENCE_API_TOKEN=...                      # CONFLUENCE_SSL_VERIFY=false for an internal CA
```

The server branches internally where the two products' APIs diverge. The agent
calls `confluence_search`, `confluence_get_page` and the rest either way.

## What else was considered

| Candidate | Cloud | Data Center | Verdict |
|---|---|---|---|
| **`sooperset/mcp-atlassian`** — Python, MIT, ~5.9k★, v0.23.1 (2026-08-19) | ✅ API token, OAuth 2.0 3LO | ✅ **PAT + mTLS, Confluence 6.0+** | **Chosen** |
| **Atlassian Rovo MCP Server** — official, GA, `mcp.atlassian.com/v2/mcp` | ✅ OAuth 2.1 / API token | ❌ **Cloud only** | Rejected |
| `b1ff/atlassian-dc-mcp` — TypeScript, ~95★ | ⚠️ partial | ✅ DC-focused | Rejected — separate package per product, different tool names |
| `aashari/mcp-server-atlassian-confluence` — ~61★ | ✅ | ❌ | Rejected — Cloud only, ~9 months stale |
| `cosmix/confluence-mcp` — ~12★ | ✅ | ❌ | Rejected — **repository archived** |
| `KS-GEN-AI/confluence-mcp-server` — ~14★ | ✅ | ❌ | Rejected — three tools |
| `zereight/confluence-mcp` — ~29★ | ? | ? | Rejected — **no licence** |

The official Atlassian server is the most polished thing on that list, and it is
still the wrong choice here. It is Cloud-locked, metered in Rovo credits, gated
behind an org admin, and its tool names (`getConfluenceContent`,
`searchConfluence`, `createConfluenceContent`) share nothing with any DC-capable
server. Adopting it today would build in exactly the lock-in this repository set
out to avoid.

### Atlassian ships no MCP server inside Data Center

Checked against the Confluence DC upgrade matrix and the Data Center roadmap.
Confluence DC 9.4 added a *Rovo connector*, which indexes DC content into
Atlassian Cloud. That is not an on-premise MCP endpoint. Atlassian's AI strategy
for Data Center is "connect DC to Cloud Rovo", not "run a server on-premise".

## Guardrails

These are not general advice. Each one comes from something that has actually
gone wrong with this server.

**Pin `>= v0.23.1`.**

| Advisory | Effect | Affected |
|---|---|---|
| CVE-2026-27825 (CVSS 9.1) | arbitrary file write → RCE via an unvalidated `target_path` in `download_attachment` | `< 0.17.0`, HTTP transport |
| CVE-2026-27826 (CVSS 8.2) | SSRF via unvalidated URL headers | `< 0.17.0`, HTTP transport |
| GHSA-5j8j-256g-vvp5 | `--transport sse` bypassed the auth middleware entirely | `< 0.23.1` |

**Use the Cloud API token, not Cloud OAuth.** Atlassian removed the v1 REST
endpoints from the `api.atlassian.com` gateway around 2026-08-17; they now answer
`410 Gone`, which breaks the server's Cloud OAuth path (upstream issue #1598,
still open). Direct API-token access is unaffected — and it is also the closest
thing to the Data Center PAT, so the two deployments stay similar.

**Avoid the `sse` transport.** Use `stdio` for the lab, `streamable-http` for a
remote topology.

**Keep `ALLOW_GLOBAL_CRED_FALLBACK` disabled.** With it on, an unauthenticated
caller executes tools with the operator's credentials.

**Narrow the surface.** `READ_ONLY_MODE=true` and
`TOOLSETS=confluence_pages,confluence_comments` remain the delivered defaults.
The server exposes around 98 tools across Jira and Confluence; the agent needs
ten.

The agent now delivers four write capabilities, each gated by the confirmation
policy and two of them additionally pinned by the security floor. That changes
nothing here: `READ_ONLY_MODE` is the server's own switch, and leaving it `true`
means a misconfigured agent still cannot write. Set it to `false` deliberately,
when writing is what the deployment is for. The delivered toolsets already carry
the page and comment tools those capabilities need.

## Identity is the hard part

A wiki restricts pages and spaces per person. This has one consequence that
dominates every other integration decision:

> The MCP server must carry the identity of the person asking. Never a shared
> service account.

An agent running as a service account would read pages the user is not allowed to
see, and would summarise them back to that user in perfect good faith. Both HTTP
transports support per-request authentication for exactly this — `Authorization:
Basic ...` for Cloud, `Authorization: Token <PAT>` for Data Center.

The corollary is that a refusal is a **normal answer**, not an incident. The
contract keeps "no such page" and "you may not read this page" distinct
(`wiki_not_found` against `wiki_access_denied`), because collapsing them would
have the agent telling people documentation does not exist when in fact they
simply cannot see it.

## Everything a wiki returns is untrusted

Page bodies, titles, excerpts, comments, space names, labels, version messages.
All of it is wrapped as `UntrustedText` at the dialect boundary, without
exception.

This matters more on a wiki than on a mailbox. An email is read once by one
person; a page is durable, edited by many, often reachable by externals, and a
payload planted in it is read by every future question that touches it. The
delivered dataset carries a planted instruction on `apollo-onboarding` precisely
so this cannot be quietly forgotten.

## Servers

| | `mock` | `wiki-local` | `mcp-atlassian` | `mcp-atlassian-http` |
|---|---|---|---|---|
| Backed by | JSON dataset | JSON dataset | a real Confluence | a real Confluence |
| Protocol | none | MCP over stdio | MCP over stdio | MCP over streamable HTTP |
| Server | — | ours | `sooperset` | `sooperset` |
| Credentials | none | none | API token or PAT | per user, in a header |
| Identity | the caller | the caller | **one person** | **the caller** |
| Dialect | — | `native` | `atlassian` | `atlassian` |

The last row is the one that matters. Over stdio the server holds one credential
and acts as one person; over streamable HTTP it reads an `Authorization` header
on every request and acts on behalf of whoever it names. Same server, same tools,
same dialect — a different identity model.

The reference server (`wiki-mcp-reference`) exists so a real MCP client can be
exercised over a real protocol stack with no network, no credentials and no
Confluence. It reproduces page and space restrictions, because a double that let
everyone read everything would let a client pass a conformance suite it would
fail in production.

## Running mcp-atlassian

It is not vendored. It is a third-party server, run as one.

Over stdio, started by the agent:

```bash
docker run --rm -i \
  -e CONFLUENCE_URL=https://your-site.atlassian.net/wiki \
  -e CONFLUENCE_USERNAME=you@corp.example \
  -e CONFLUENCE_API_TOKEN=... \
  -e READ_ONLY_MODE=true \
  -e TOOLSETS=confluence_pages,confluence_comments \
  ghcr.io/sooperset/mcp-atlassian:0.23.1
```

Over streamable HTTP, started once and shared:

```bash
docker run --rm -p 9000:9000 \
  -e CONFLUENCE_URL=https://your-site.atlassian.net/wiki \
  -e CONFLUENCE_PERSONAL_TOKEN=unused \
  -e READ_ONLY_MODE=true \
  -e TOOLSETS=confluence_pages,confluence_comments \
  ghcr.io/sooperset/mcp-atlassian:0.23.1 \
  --transport streamable-http --host 0.0.0.0 --port 9000
```

The credentials live in that process and nowhere else. They never reach the
agent, a prompt, a log or a trace. In the HTTP case the environment credential is
a placeholder that only supplies the base URL, the SSL settings and the proxy
settings; each request carries the real one.

See [wiki-agent-running.md](./wiki-agent-running.md) for the header formats and
for what an unauthenticated request gets (a 401, by default, which is the right
answer).

## Adding another wiki system

Notion, XWiki, SharePoint: the same three steps as any other server, described in
[repository-structure.md](./repository-structure.md). Write a dialect, register
it, deliver a binding. The domain speaks of spaces, pages and comments, and it
has never heard of Confluence.
