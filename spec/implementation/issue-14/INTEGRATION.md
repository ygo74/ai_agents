# Issue 14 — verification report (2026-11-21)

## Environment and dependency provenance

- Agent interpreter: Python 3.14 in `/tmp/issue14-agent`.
- Runtime agents/security/agentframework: 0.9.0, built from the existing sibling
  checkout `/data/repos/ai-enterprise-agent-runtime`; upstream repository:
  https://github.com/ygo74/ai-enterprise-agent-runtime.
- Framework core: 1.18.0; framework OpenAI: 1.14.3; MCP SDK: 1.30.0.
- Official server: `edgartools[ai]==6.3.0` from the package index, in a separate
  `/tmp/issue14-server` environment. Entry point: `edgartools-mcp --transport stdio`.
- Server identity was supplied by the user through its process environment;
  contact details are intentionally not copied into tracked configuration.
- Writable local SEC cache: `/tmp/issue14-edgar-data`; configured rate: 5/second.
- Initial dev312 runtime metadata reported 0.8.2, below the required minimum.
  Python 3.12 verification subsequently used the sibling runtime 0.9.0 public
  source paths explicitly, without claiming that the old installed wheel was updated.

## Discovery

Actual MCP `initialize` returned server `edgartools` version `6.3.0`.
Actual `list_tools` confirmed `edgar_search` and `edgar_company` and their input
schemas. Captured schema fixture:
`tests/integration/credit/edgartools-6.3.0.schemas.json`.
The adapter also discovers and validates the schemas on its first call.
No model API or direct agent-side SEC HTTP access was used for discovery.

The restricted local environment blocked stdio initialization; the same
connection completed outside those restrictions after authorization. An initial
server cache error was resolved with `EDGAR_LOCAL_DATA_DIR`, without changing
home-directory permissions. These attempts are not counted as successful SEC
identifications.

## Real SEC identification through the local MCP

| Input | Type | Outcome | SEC legal name | Normalized CIK |
|---|---|---|---|---|
| `aapl` | ticker | identified | Apple Inc. | `0000320193` |
| `320193` | cik | identified | Apple Inc. | `0000320193` |
| `0000320193` | cik | identified | Apple Inc. | `0000320193` |
| `Apple Inc.` with selected_cik `320193` | name | identified | Apple Inc. | `0000320193` |

The first successful profile retrieval was recorded at
`2026-11-21T08:18:44.401267Z` (09:18 Paris). The supplementary CIK/name
verification completed around `08:28:22Z` (09:28 Paris).
Returned ticker: AAPL; SIC: 3571; SIC description: Electronic Computers.
Sources:

- https://www.sec.gov/files/company_tickers.json (company search reference)
- https://data.sec.gov/submissions/CIK0000320193.json (issuer metadata)

Each populated profile field references a response source identifier. Retrieval
timestamps denote successful MCP retrieval, potentially using the server's
cache/bundled reference, not a fresh SEC download. Publication date is null.
Exchange remains null because the exposed tool does not guarantee its association
with a ticker. Sector/origin remain null because there is no independent sourced
sector/mapping. Both limitations are reported in warnings. No credit decision
was produced. The composition closed its MCP resources after the calls.

## Reproducible checks

- First business tests failed because the new port/module did not exist, then
  passed after implementation (12 initial cases).
- First MCP adapter tests failed because the adapter module did not exist,
  then passed after implementation.
- Final new-agent test suite: 25 passed, including normalization, ambiguity,
  selection, duplicate issuers, missing metadata, truncation, contradictory
  profiles, source validation, safe logs, MCP failures/schema allowlist,
  bounded retries, SDK timeout classification, and native MAF tool invocation.
- Python 3.12 new-agent plus existing MAF registration checks: 36 passed.
- Python 3.14 new-agent, runtime-source installer, repository architecture,
  and existing MAF registration checks: 1497 passed, 900 skipped.
  Architecture skips are the suite's normal module/layer applicability filters.
- Ruff check passed for changed Python source/tests and installer/architecture.
- Strict mypy passed for credit plus the new MAF composition module (22 files).
- Credit and MAF wheels built and installed successfully; `credit-agent --help`
  and the installed structured validation path ran successfully. `pip check`
  reported no broken requirements.
- Native MAF actually called `identify_company` using the runtime capability
  descriptor and a scripted model; this was not a mocked framework invocation.
  No real model credentials were required or supplied for this verification.

The source test invocation used all repository distribution source roots on
`PYTHONPATH` because the temporary agent environment intentionally did not
install other agents. Omitting the Mail protocol root initially caused an
unrelated optional-dependency import probe to fail; with the normal development
source roots present, the full applicable scope passed.

## Practical limitations

The official server's search uses a finite SEC ticker reference; no result is
not proof of company nonexistence. Truncated searches require selection/refinement.
Only explicit `COMPANY_NOT_FOUND` business codes are interpreted as no-match;
uncoded profile errors cannot be safely distinguished and are reported as
invalid MCP responses. SEC transport/rate/cache behavior is server-owned.
The adapter handles typed transient failures conservatively, without a fallback
HTTP path. The conversational integration is tested with a scripted model; a
live model call requires the operator's provider credentials and model routing.

## Full pre-commit gates (Python 3.12)

On the user's explicit commit/push request, the complete repository checks ran:
`python -m ruff check .`, `python -m mypy`, and `python -m pytest` with JUnit XML
written outside the repository. Ruff passed; strict mypy passed on 268 files;
the complete test suite passed: 2641 passed, 900 applicability skips,
27 existing endpoint-deprecation warnings, 171.13 seconds. The runtime's public
source paths matched the local V0.9.0 tag. The delivered-binding coverage test
was extended to load and cover edgartools alongside Mail/Wiki; its 70 checks
passed before the full suite reran. Local MCP tests required authorized execution
outside the restricted environment. The XML was not included in the commit.
