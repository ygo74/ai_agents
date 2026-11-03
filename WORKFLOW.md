# Repository Development Workflow

`AGENTS.md` contains always-loaded architecture and security principles. Start
new requests from the consolidated current behavior in [`spec/README.md`](spec/README.md),
then load only the relevant Mail/Wiki and framework references. Keep request
tracking records under `spec/implementation/` in the primary repository; do not
link them from user-facing documentation.

## Lifecycle

```text
user request or optional Issue
  → SPEC → user approval → PLAN → user approval → TASKS
  → test-driven implementation → review and user acceptance
  → requested consolidation, user/contributor docs, and release work
```

Use the local `development-workflow` skill as the entry point. An Issue is
optional and must not be created unless the user asks.

The specification skill loads the Business Analyst role for a primarily
functional Mail/Wiki agent capability, and the Python Solution Architect role
for a primarily technical change such as framework integration, shared runtime
use, or architecture. It records scope, expected behavior, acceptance criteria,
constraints, and open questions, then waits for SPEC approval. The planning
skill analyzes existing modules, tests, contracts, configuration, and docs;
it presents the PLAN and waits for approval. After approval, the architect
creates `TASKS.md`; there is no third approval gate.

Implementation follows the approved tasks with failing test, minimal change,
passing test, and refactor for behavior changes. The code stays typed, simple,
framework-native at the adapter edge, and easy to debug. Update task status and
the canonical journal as work proceeds. Submit discovered improvements to the
Solution Architect to classify as in-scope or a separate user proposal.

## Repository architecture

- Mail domain models, permissions, untrusted origins, deterministic services,
  and security floor remain application-owned; its framework adapter is
  Microsoft Agent Framework.
- Wiki owns its graph, tool admission, permission policy, confirmation tickets,
  MCP dialect, and capability filtering; it uses LangChain/LangGraph.
- Keep framework-independent skills separate from framework session/tool
  adapters. Use public framework APIs and the `ai-enterprise-agent-runtime`
  contracts rather than private wrappers or duplicate runtime code.
- MCP is the sole integration boundary to enterprise systems. Credentials and
  transport configuration stay in infrastructure.
- Preserve caller scoping, deterministic write confirmation, untrusted-content
  fences, one-use tickets, and identifier-only audit logging.
- Keep Mail and Wiki framework distributions isolated; maintain deterministic
  mock compositions and architecture tests.

After user acceptance, invoke system consolidation, user or contributor docs,
and image version preparation only when requested or included in the approved
plan. Pushing a `v*` tag triggers image publication and needs explicit user
authorization. Never merge a pull request or publish implicitly.
