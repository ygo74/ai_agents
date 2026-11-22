# Corporate Credit Analyst: SEC issuer identification

This Python agent assists an analyst by identifying a company in EDGAR. It does
not approve/refuse credit or perform financial analysis. A deterministic skill
confirms the identity using the official EdgarTools MCP server; Microsoft Agent
Framework interprets conversational requests and calls that same skill.

To call this agent from LibreChat, OpenAI SDKs or other HTTP clients, see
[serving the Credit agent over HTTP](credit-agent-http.md).

## Install isolated environments

Use Python 3.12 or later. From the repository root:

```bash
python3.12 -m scripts.install --env credit-agent --into .venvs/credit-agent
python3.12 -m venv .venvs/edgartools-server
.venvs/edgartools-server/bin/python -m pip install 'edgartools[ai]==6.3.0'
```

If the runtime version is not available on your package index, use the sibling
runtime checkout (version 0.9.0) explicitly:

```bash
python3.12 -m scripts.install --env credit-agent --into .venvs/credit-agent \
  --runtime-source /absolute/path/to/ai-enterprise-agent-runtime
```

Runtime source: <https://github.com/ygo74/ai-enterprise-agent-runtime>. Public
packages used are `ygo74-agent-runtime-agents[configuration,mcp]`,
`ygo74-agent-runtime-security`, and the MAF adapter's
`ygo74-agent-runtime-agentframework`. Required runtime range is >=0.9.0,<2.
The server is from <https://github.com/dgunning/edgartools>, specifically
`edgar.ai.mcp.server`. Installing the library without its `[ai]` extra does not
install its MCP dependencies. Keep this server separate from the agent.

Verified combination for this delivery: Python 3.14, runtime 0.9.0 built from
the sibling checkout, `agent-framework-core` 1.18.0,
`agent-framework-openai` 1.14.3, MCP SDK 1.30.0, EdgarTools 6.3.0.
Python 3.12 also passed business, MCP adapter and scripted MAF integration tests;
the real SEC/MCP network verification used 3.14.
See the [integration report](../../spec/implementation/issue-14/INTEGRATION.md).

## Configuration and SEC identity

Copy `config/agents/credit/.env.example` to `.env`, replace its placeholders,
and set `CREDIT_MCP_COMMAND` to the absolute path of
`.venvs/edgartools-server/bin/edgartools-mcp`. Alternatively edit the `command`
and `args` in `config/mcp/edgartools.yaml`. `--config /absolute/path/to/config`
or the runtime's `YGO74_AGENT_RUNTIME_CONFIG_DIR` selects the delivered directory.

Provide your actual organization/name and contact email in `EDGAR_IDENTITY`.
Use a writable `EDGAR_LOCAL_DATA_DIR` for server caches; no application-owned
candidate state is retained. `EDGAR_RATE_LIMIT_PER_SEC=5` configures a
conservative per-process SEC rate. EdgarTools implements its SEC identity,
cache and blocking rate limiter (default 9 requests/second). Multiple server
processes share the SEC access limit in practice: do not scale independently
without coordinating the aggregate rate. SEC APIs require no SEC API key.

The model SDK reads `OPENAI_API_KEY`, or `AZURE_OPENAI_API_KEY` for Azure.
Set `CREDIT_MODEL`, `CREDIT_MODEL_PROVIDER` (`openai` or `azure_openai`), and
for Azure `CREDIT_AZURE_ENDPOINT` plus optional `CREDIT_AZURE_API_VERSION`.
Nonsecret defaults and bounded retries are in
`config/agents/credit/settings.yaml`. Never put credentials in YAML or queries.
The structured mode and MCP discovery do not require model credentials.

## Local use

Stdio starts the server automatically and closes it after the request:

```bash
.venvs/credit-agent/bin/credit-agent --config config --discover
.venvs/credit-agent/bin/credit-agent --config config --query aapl --query-type ticker --json
.venvs/credit-agent/bin/credit-agent --config config --query 320193 --query-type cik --json
.venvs/credit-agent/bin/credit-agent --config config --query 0000320193 --query-type cik
.venvs/credit-agent/bin/credit-agent --config config --query 'Apple Inc.' --query-type name
.venvs/credit-agent/bin/credit-agent --config config --query 'Apple' --query-type name --selected-cik 320193
.venvs/credit-agent/bin/credit-agent --config config --message 'Identify Apple by ticker AAPL'
```

The last command uses native MAF and the configured model. Only the
`identify_company` business tool is exposed to the model; financial, filing,
ownership and other server tools are not exposed. Tool JSON is fenced as
untrusted SEC data. The structured modes return validated skill output directly,
without having a model rewrite the facts. Human-readable output includes the
identity, limitations and sources. Errors exit with status 1.

`auto` interprets ASCII digits as CIK, a short ASCII word containing only letters,
periods or hyphens as ticker, and other text as a company name. Use `--query-type
name` for short company names that resemble tickers. CIK must be nonzero and
contain at most ten ASCII digits; output is always a ten-digit string.

Ambiguous results contain distinct CIK candidates without a confirmed company.
Repeat the original query/type with `--selected-cik` from that list. The agent
reruns the search and checks membership, then retrieves the selected profile;
results may change between searches. A selection outside the current results is
rejected. No candidate list is retained between CLI invocations.

## Joining an already-running local server

Start the official server separately:

```bash
.venvs/edgartools-server/bin/edgartools-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Use the following transport fields in a copy of `config/mcp/edgartools.yaml`,
keeping its capabilities, dialect and tool allowlist:

```yaml
transport: http
url: http://127.0.0.1:8000/mcp
```

Remove `command`/`args` for HTTP. Configure `EDGAR_IDENTITY` and cache/rate
variables in the server process for this mode. The official local server does
not provide authentication by default; the runtime loader supports configured
API-key/OAuth headers when the chosen server supports them. The local credit
composition does not enable delegated caller authentication.

## Result and known limitations

Results contain `status`, normalized `query`/resolved `query_type`, `company`,
`candidates`, `sources`, `warnings`, and `error`. States are `identified`,
`ambiguous`, `not_found`, and `error`. Profile scalars absent from SEC are null;
collections are empty. Legal name/CIK and every populated profile field have
source references. SIC and `industry` from the server are represented as
`sic_code` and `sic_description`. No sector mapping or independent sector is
inferred. Exchange lists are not paired with ticker lists by position, so an
unknown association is null even when the server lists exchanges separately.

Name/ticker searches use the SEC ticker reference, which EdgarTools can serve
from a bundled/cache copy; non-listed issuers can be absent. A search reaching
the configured limit cannot automatically establish uniqueness. Source URLs
are canonical SEC dataset/submissions URLs constructed from the server's
verified data provenance, not additional HTTP requests by the agent.
Timestamps describe the adapter's successful MCP retrieval, not a guaranteed
fresh SEC download or publication date. No publication date is invented.

`not_found` means no result in the EDGAR search performed. It does not establish
that a company does not exist. Errors distinguish invalid input, unavailable
server, timeout, SEC access and invalid/incomplete MCP data. The official server
sometimes suppresses typed exceptions into free-text errors; an unclassified
profile failure is reported as an invalid MCP response, never guessed to be
`not_found`. Explicit typed rate-limit/service errors permit bounded retries
respecting `retry_after`; uncoded SEC failures are not retried automatically.
Transport timeouts/unavailability permit at most the configured attempts
(default 2, maximum 3), in addition to the separately bounded runtime/server
transport policy. There is no direct SEC HTTP fallback.

Application logs contain correlation, tool, duration, attempt and outcome without
full queries, profiles or secrets. The upstream server manages its own logging
and SEC caching. See contributor documentation for reproducible tests.
