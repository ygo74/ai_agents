# Implementation Tasks

- [x] ADHOC-MCP-001 Add failing tests for MCP CLI argument parsing, environment-sourced headers, schema rendering, list-only behavior, error exit status, and cleanup; repository: `ai_agents`; completion: the tests describe the approved behavior and fail against the current code; depends on: none.
- [x] ADHOC-MCP-002 Implement the Streamable HTTP inspector CLI; repository: `ai_agents`; files: `scripts/inspect_mcp.py`; completion: `python -m scripts.inspect_mcp` lists live tool metadata, never invokes a tool, avoids credential output, and closes resources after success or error; depends on: ADHOC-MCP-001.
- [x] ADHOC-MCP-003 Document Mail and Wiki usage; repository: `ai_agents`; file: `doc/contributors/mcp-clients.md`; completion: HTTPS examples show the environment sourced Mail bearer header and Wiki API-key header; depends on: ADHOC-MCP-002.
- [x] ADHOC-MCP-004 Run focused quality checks and review the change; repository: `ai_agents`; completion: Ruff and the focused pytest module pass, and actual results and any deviations are recorded in `JOURNAL.md`; depends on: ADHOC-MCP-001, ADHOC-MCP-002, ADHOC-MCP-003.
