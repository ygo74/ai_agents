# Corporate Credit Analyst

The Python Corporate Credit Analyst identifies an SEC issuer by company name,
ticker or CIK via the official local EdgarTools MCP server. It assists an
analyst and never takes a credit decision. Financial analysis and credit note
generation are future capabilities.

Domain/application rules are deterministic. The confirmed profile requires a
legal name, normalized ten-digit CIK, consistent metadata and SEC source
references. Search results are deduplicated by CIK; ambiguity requires explicit
analyst selection verified against a fresh search. A model cannot choose an
ambiguous issuer, infer a sector, authorize access or replace confirmed facts.

The agent uses Microsoft Agent Framework for conversation, a runtime capability
registry for the identification tool and the runtime's configuration,
permissions, invocation correlation and MCP connection mechanics. External
content is untrusted data. MCP access is restricted to `edgar_search` company
metadata and `edgar_company` profile retrieval; no direct SEC HTTP fallback.
The structured entry point executes the same typed skill without model inference.

The runtime-managed HTTP host exposes authenticated OpenAI Chat Completions,
Responses (normal and streaming) and model discovery. The delivered manifest
uses an API key; JWT/OIDC is configurable. Verified subjects receive the
read-only identification permission and scope their native MAF sessions by
conversation ID. A bounded runtime cache owns session/MCP resources and closes
them on eviction or shutdown; it does not persist history across restarts.
See the [HTTP client guide](../../doc/users/credit-agent-http.md).

See [user guide](../../doc/users/credit-agent.md),
[contributor architecture](../../doc/contributors/credit-agent.md), and the
[contract implementation](../../agents/credit/src/ai_agent_lab/credit/domain/models.py).
