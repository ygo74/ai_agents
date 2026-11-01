# Code review implementation tasks

## Review context

- Branch: `feature/34-agent-http-manifest`.
- Reviewed commit: `0d03b59b0e342fbf42939bf27d4b5f511e340a0a`.
- Base: local `origin/main`; merge base `0ad1d4604b539436c4c2154d8c28716b8705f5b4`. No remote fetch was performed.
- Scope: final development-branch changes, including staged, unstaged and relevant untracked Mail/Wiki routing code. Overlapping changes were reviewed once. This is not limited to the most recent registry work.
- Status: complete for the bounded review below. HTTP end-to-end validation is blocked by CR-003. No claim of complete security assurance is made.
- Only this report was written during the review. Production code and the original Git index were preserved.

### Reviewed files and boundaries

The review followed callers into the directly related ports, capabilities, settings, authorization adapters and runtime APIs:

- Mail bootstrap: [composition](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/composition.py), [provider](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/mail_tools_provider.py), [factory](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/skills_factory.py), [router](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/routed_mail_tools.py), [scope wrapper](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/scoped_mail_tools.py), and [HTTP service](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/service.py).
- Wiki bootstrap: [composition](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/composition.py), [provider](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/wiki_tools_provider.py), [factory](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/skills_factory.py), [router](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/routed_wiki_tools.py), [scope wrapper](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/scoped_wiki_tools.py), and [HTTP service](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/service.py).
- Wiki [MCP registry loader](../../../../../../agents/wiki/src/ai_agent_lab/wiki/infrastructure/mcp/registry.py), [configuration](../../../../../../agents/wiki/src/ai_agent_lab/wiki/infrastructure/mcp/configuration.py), [authoring skill](../../../../../../agents/wiki/src/ai_agent_lab/wiki/application/skills/authoring_skill.py), [search skill](../../../../../../agents/wiki/src/ai_agent_lab/wiki/application/skills/search_skill.py), and [read descriptors](../../../../../../agents/wiki/src/ai_agent_lab/wiki/adapters/capabilities/read_capabilities.py).
- Changed agent/skill manifest declarations and relevant MCP authentication configurations; related Mail/Wiki HTTP, routing, exposure, environment-selection, confirmation and security tests. Shared [dependency declarations](../../../../../../agents/core/pyproject.toml) were checked against the installed editable runtime.
- Relevant architecture and changed configuration/HTTP/routing documentation: [architecture](../../../../architecture.md), [MCP clients](../../../../mcp-clients.md), [Mail](../../../../mail-agent.md), [Wiki](../../../../wiki-agent.md), [operator configuration](../../../../../users/configuration-and-deployment.md), [configuration reference](../../../../../users/configuration-reference.md), and the Mail/Wiki HTTP and deployment guides.
- Excluded: unrelated unchanged code, a full audit of the external runtime repository, live enterprise systems, deployment infrastructure, model-quality benchmarks, and the newly created review skill itself. Runtime source was read only where needed to understand the registry/worker contracts. User launch settings were not changed.

## Summary

- Simplicity: one avoidable full-port stand-in and two functional integration problems. Keep the routing and scoped adapters: selecting a server and enforcing allowed aliases are different, necessary responsibilities.
- Security: one high-severity upstream identity-isolation weakness in legacy Wiki authentication, verified with controlled fakes. The default single-user API-key deployment is not claimed to be vulnerable to cross-user access.
- Comments: several changed provider contracts describe behavior that the implementation no longer follows.

## Remediation progress

The review evidence below describes the state before these corrections.

| Task | Outcome |
|---|---|
| CR-001 | Fixed legacy credentials are bound to `WikiAgentSettings.user_id`. An injected `WikiUserCredentials` source stays caller-bound and fails closed for unknown users. Provider/registry/Atlassian regressions pass. Two-subject JWT HTTP regressions verify `get_page` and `summarise_page`: unauthorized subjects receive 403 before retrieval or reasoning. |
| CR-002 | Grouped standalone Wiki reads use each operation's own manifest skill. Single-server, two-server, real-composition descriptor, and reasoning-isolation tests pass. |
| CR-003 | The editable runtime was fast-forwarded to its existing upstream commit `e097cac`, which supports `WorkerSettings.http_settings`. All previously failing HTTP/environment tests pass. Seven direct runtime contract tests verify manifest policy selection, rejected conflicting security settings, legacy construction, and lifecycle cleanup. The implementation guide names the verified source commit and required API; compatibility with a published release remains unverified. |
| CR-004 | The repeated unavailable full-port adapter was removed. The existing router uses a fixed failing resolver for missing skills, preserving lazy startup and explicit invocation errors. |
| CR-005 | Provider/router comments now distinguish legacy fallback, operation routing, fixed reasoning scopes, and fixed-owner versus caller-bound credentials. |

Final validation: **343 tests passed**: 328 combined regressions across 19 targeted
files, plus 15 existing Wiki conversation lifecycle tests. There is one existing
Starlette/AnyIO deprecation warning. Ruff passes. Mypy passes on eleven production
files with the
documented editable-runtime source roots and `--follow-imports=silent`, retaining
imported type information without auditing the external runtime source.

See the [credential ownership tests](../../../../../../tests/security/test_wiki_credential_ownership.py),
[HTTP credential ownership tests](../../../../../../tests/security/test_wiki_http_credential_ownership.py),
[worker HTTP contract tests](../../../../../../tests/contract/test_worker_settings_http_contract.py),
[Wiki routing tests](../../../../../../tests/unit/wiki/test_wiki_registry_routing.py),
[runtime prerequisites](../../../../implementing-an-agent.md), and
[operator credential guidance](../../../../../users/configuration-and-deployment.md#keep-wiki-credentials-bound-to-their-owner).

## Implementation tasks

### CR-001 — Bind legacy Wiki credentials to their authorized caller

- Category: security.
- Priority: P1.
- Confidence: high.
- Security severity: HIGH.
- Locations: [connection authorization construction](../../../../../../agents/wiki/src/ai_agent_lab/wiki/infrastructure/mcp/registry.py#L42), [per-user classification](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/wiki_tools_provider.py#L375), and [Atlassian account-owner guard](../../../../../../agents/wiki/src/ai_agent_lab/wiki/infrastructure/mcp/atlassian/client.py#L318).
- Evidence and impact: the security specialist verified that two distinct subjects receive identical upstream authorization headers made from deployment-wide `user_account`/`user_secret`. The provider marks these adapters as per-user, so the account-owner guard is skipped. Both subjects reached a mocked page read using the configured account. A further offline check through the actual factory and composition resolver confirmed that the second subject can retrieve owner-credential content through `summarise_page` and pass it to the reasoner, independently of CR-002. Preconditions are a functioning multi-user JWT host, the legacy `mcp-atlassian-http` binding, and configured basic/token/bearer account credentials. An authenticated caller can inherit another account's restricted Wiki access. Write confirmation does not repair that identity mismatch. This is a previously acknowledged gap, not evidence that the newest registry work introduced the original problem. HTTP end-to-end reachability remains blocked by CR-003.
- Implementation:
  1. Associate fixed upstream credentials with an explicit authorized subject. Reject other subjects before constructing or exposing a connection using those credentials.
  2. Do not classify a deployment-wide credential as caller-bound merely because its authorization scheme is non-`none`.
  3. Permit genuine multi-user use only with a caller-bound credential source. Fail closed when that source has no credential for a subject; do not fall back to the deployment account.
  4. Correct the documented single-user versus multi-user contract together with the code. Do not build a new generic authentication framework for this task.
- Preserve: credentials remain behind the MCP boundary; normal owner access, source-system ACLs, operation policy, confirmation, one connection per server per caller/session, and explicit runtime authentication modes.
- Dependencies: none for the provider-level fix; CR-003 is needed for HTTP regression validation.
- Validation: extend the existing controlled tests in [Wiki registry routing](../../../../../../tests/unit/wiki/test_wiki_registry_routing.py) and the existing Wiki security suites. A second subject must neither obtain the fixed owner's credential nor invoke its tools. Test owner success, distinct caller-bound credentials, and missing-credential refusal. After CR-003, exercise two authenticated HTTP subjects with mocked MCP calls.
- Acceptance criteria: fixed credentials are usable only by their admitted owner; genuinely caller-bound credentials stay distinct; rejected callers cause zero upstream calls; no credential appears in prompts, errors or test reports.

### CR-002 — Route every standalone Wiki read through its own manifest skill

- Category: simplicity (incorrect composition of an existing routing abstraction).
- Priority: P1.
- Confidence: high.
- Locations: [grouped search-skill construction](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/skills_factory.py#L182), [standalone read descriptors](../../../../../../agents/wiki/src/ai_agent_lab/wiki/adapters/capabilities/read_capabilities.py#L120), [lazy fixed-skill resolver](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/composition.py#L298), and [existing operation router](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/routed_wiki_tools.py#L22).
- Evidence and impact: `DocumentationSearchSkill` implements search, page, children, spaces, comments and history reads, but the factory supplies only the `search_wiki` adapter. With the real provider/registry and its existing fake-server fixture, calls through `skills.search.get_page`, `get_children` and `list_spaces` each raised `McpBindingError`: `search_wiki` does not declare the requested alias. Zero remote reads occurred. The default-startup test calls the provider directly, and the operation-routing test calls `provider.build()`: neither crosses the faulty factory wiring. An agent can advertise a page-read capability that fails when invoked.
- Implementation:
  1. Inject the existing `RoutedWikiTools` backed by the factory's per-skill resolver into the grouped `DocumentationSearchSkill`, as Mail already does for grouped operations.
  2. Keep the composition resolver lazy for missing/withdrawn skills. Do not broaden `search_wiki.mcp_tools` to hide the error or choose an arbitrary first server.
  3. Keep reasoning and authoring skills on their own fixed skill selection; do not route their internal reads using standalone read overrides.
  4. Add factory/composition-level coverage, not just direct provider coverage.
- Preserve: skill override → agent default, alias checks, caller context, read-only filtering, shared connections and closure checks. Reasoning skills retain their own server across all their calls.
- Dependencies: none.
- Validation: extend [Wiki registry routing tests](../../../../../../tests/unit/wiki/test_wiki_registry_routing.py). Invoke all grouped read operations through `WikiSkillsFactory` and at least one exposed descriptor through real composition. Test both a single-server manifest and two servers with different read-skill overrides. Keep missing-history startup coverage and reasoning-skill isolation coverage.
- Acceptance criteria: all exposed standalone reads reach the adapter selected by their own manifest skill; the default page read succeeds against a fake server; undeclared aliases are still rejected; missing skills do not break startup.

### CR-003 — Reconcile manifest-driven HTTP setup with the supported runtime worker API

- Category: simplicity (broken typed integration contract).
- Priority: P1.
- Confidence: high.
- Locations: [Mail worker construction](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/service.py#L88), [Wiki worker construction](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/service.py#L90), [runtime dependency range](../../../../../../agents/core/pyproject.toml#L21), and [agent implementation guide](../../../../implementing-an-agent.md).
- Evidence and impact: both services pass `http_settings` to `WorkerSettings`. In the installed editable runtime, its signature requires `authentication`, supports `surfaces`, and does not accept `http_settings`. The combined HTTP/environment check produced 24 failures and 41 passes; startup fails with `TypeError: WorkerSettings.__init__() got an unexpected keyword argument 'http_settings'`. This predates the latest registry work but is inside the development-branch HTTP migration under review. The HTTP entrypoints are unusable in the current environment.
- Implementation:
  1. Recheck the intended runtime version and its actual public worker API. Align both services with that supported contract using the smallest composition change, or require a verified runtime release that provides the intended contract.
  2. Ensure the declared dependency range and editable development setup support the selected API. Do not silently claim compatibility with a version that lacks it.
  3. Preserve the complete manifest policy, including selected surfaces and any declared rate limits. Do not simply drop the rejected argument, disable authentication, or add a broad `TypeError` fallback.
  4. Update the directly related implementation guide if worker construction changes. Keep runtime-owned HTTP concerns out of agent domain code.
- Preserve: manifest-selected authentication/endpoints, authenticated discovery, per-caller conversation isolation, lifecycle cleanup, bounded conversation counts, and environment-selected manifests.
- Dependencies: none.
- Validation: rerun the six existing files listed in validation evidence below. Assert Mail and Wiki API-key startup, JWT startup/cleanup, selected endpoint exposure, denied unauthenticated access, and alternate manifest selection. Run against the supported development dependency, not a monkeypatched worker constructor.
- Acceptance criteria: both real service factories build; no unsupported worker keywords remain; the 24 recorded startup failures are resolved without policy weakening; supported dependency expectations are explicit and reproducible.

### CR-004 — Reuse the lazy router instead of reimplementing the whole unavailable Wiki port

- Category: simplicity.
- Priority: P2.
- Confidence: high.
- Locations: [full-port stand-in](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/skills_factory.py#L53), [missing-skill fallback](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/skills_factory.py#L237), and [typed lazy router](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/routed_wiki_tools.py#L22).
- Evidence and impact: `_LazyUnavailableWikiTools` repeats every Wiki port method solely to discard parameters and raise the same error. The repository already has a typed router that resolves its delegate at invocation time. Keeping a second full-port implementation creates an unnecessary maintenance obligation whenever the port gains a method, without adding a distinct domain responsibility.
- Implementation:
  1. Replace the repeated stand-in with the existing lazy router backed by a fixed missing-skill resolver that raises the same explicit error.
  2. Keep the independent factory contract: injected resolvers are not necessarily lazy. Do not eagerly call a provider for a manifest-absent skill.
  3. Remove only imports and code made unused by this simplification. Avoid merging provider, router and alias-scope responsibilities.
- Preserve: startup with absent write/reasoning/history skills; typed ports; explicit failure on direct invocation; no fallback to another server; no connection creation for unavailable skills.
- Dependencies: CR-002, to make the intended factory routing clear first.
- Validation: use [Wiki registry routing](../../../../../../tests/unit/wiki/test_wiki_registry_routing.py) and [Wiki LangGraph integration](../../../../../../tests/integration/test_wiki_agent_langgraph.py). Add missing-skill factory coverage for a read and a write, checking successful assembly followed by explicit invocation failure and zero upstream calls.
- Acceptance criteria: the duplicate full-port stand-in is gone; missing/withdrawn-skill behavior is unchanged; no new generic abstraction or dependency is introduced.

### CR-005 — Correct stale routing, fallback and identity comments

- Category: comments.
- Priority: P3.
- Confidence: high.
- Locations: [Wiki skill lookup contract](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/wiki_tools_provider.py#L144), [legacy-path contract](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/wiki_tools_provider.py#L244), [shared adapter explanation](../../../../../../agents/wiki/src/ai_agent_lab/wiki/bootstrap/wiki_tools_provider.py#L361), and [Mail router docstring](../../../../../../agents/mail/src/ai_agent_lab/mail/bootstrap/routed_mail_tools.py#L25).
- Evidence and impact: Wiki `build_for_skill()` says an absent manifest raises, but explicitly enters the legacy path. `_build_mcp_explicit()` says a manifest with no MCP-enabled skills uses that path, while `build()` selects it only when the manifest is absent. The shared-adapter explanation says legacy headers are added to dialect context, but the custom loader adds them to the connection. The Mail router says reasoning skills use scoped tools instead, while composition supplies reasoning skills with a fixed-skill lazy router that eventually resolves the scoped tools. These comments obscure ownership and encourage incorrect reuse in future agents.
- Implementation:
  1. Rewrite only these non-obvious contracts to match the final implementation after CR-001/CR-002/CR-004.
  2. Explain operation-routing callbacks versus fixed-skill lazy callbacks, and distinguish connection authentication from dialect context and caller-bound credentials.
  3. Document when legacy standalone construction is allowed and who owns connection cleanup. Do not add narration to every forwarding method.
- Preserve: existing behavior unless changed by another confirmed task; concise comments explaining contracts and reasons.
- Dependencies: CR-001, CR-002 and CR-004.
- Validation: manually compare each changed docstring with its branches and callers; verify relative source/documentation links. Documentation-only changes need no new test run.
- Acceptance criteria: none of the cited comments contradicts the code; a maintainer can identify server selection, identity ownership, fallback behavior and lifecycle without guessing.

## Observations requiring confirmation

- Published-package support for alternate manifest filenames was not validated. The current tests use an editable runtime containing that support; operator documentation already states that a supporting release is required. Recheck a specific release before promising published-package compatibility. Do not invent a runtime version or an extra compatibility layer.
- No other confirmed security task was reported by the specialist. This does not prove the agents secure. Multi-user HTTP exploitability was not exercised end to end because service construction is currently blocked.

## Validation evidence

Commands ran with the existing development interpreter, `.venvs\dev\Scripts\python.exe`, from the repository root. No new tools, dependencies or tests were added.

1. Combined HTTP and manifest/environment validation:

   ```powershell
   .\.venvs\dev\Scripts\python.exe -m pytest tests\contract\test_mail_service_configuration.py tests\contract\test_oidc_http_lifecycle.py tests\contract\test_wiki_openai_http_surface.py tests\integration\test_agent_manifest_selection.py tests\integration\test_mail_environment_selection.py tests\integration\test_wiki_environment_selection.py
   ```

   **24 failed, 41 passed, 1 warning.** The failures encounter the worker constructor mismatch in CR-003; downstream HTTP expectations were not validated.

2. Real registry and Wiki integration selection:

   ```powershell
   .\.venvs\dev\Scripts\python.exe -m pytest tests\unit\test_mail_registry_routing.py tests\unit\wiki\test_wiki_registry_routing.py tests\integration\test_wiki_agent_langgraph.py -q
   ```

   **66 passed.** These passing tests do not cover the grouped factory read path reproduced in CR-002. An initial command also named a nonexistent factory test file and collected no tests; the corrected command above was run once.

3. Offline factory reproduction reused the existing `routed_backend` fixture, real `WikiSkillsFactory`, provider, registry and scope wrapper. `get_page`, `get_children` and `list_spaces` failed the `search_wiki` alias guard; remote read count was **0**. The script was run in memory, not added to the repository.

4. Runtime introspection confirmed `WorkerSettings` comes from the local editable runtime and has `authentication`/`surfaces` parameters, not `http_settings`.

5. Security specialist validation: **135 passed** in existing routing, Wiki write and Mail/Wiki security suites; a further HTTP-related selection had **28 passed, 23 failed**, blocked by the same worker API mismatch. These selections overlap other results and must not be added into a unique-test total. Its offline identity check used controlled fakes and confirmed CR-001. An initial specialist check attempted localhost MCP startup and errored; the corrected check explicitly blocked startup and mocked the read sink. No successful live-backend result was obtained. The parent did not independently rerun these specialist commands. The specialist ran the following selections through stdin-only `pytest.main(...)` launchers using `-q -p no:cacheprovider --tb=short`, bytecode disabled, and a reviewer socket guard permitting only asyncio internal self-pipe connections:

   - Successful selection: `tests\unit\test_mail_registry_routing.py`, `tests\unit\wiki\test_wiki_registry_routing.py`, `tests\unit\wiki\test_wiki_write_skills.py`, `tests\unit\wiki\test_wiki_write_capabilities.py`, `tests\security\test_mail_security.py`, `tests\security\test_wiki_security.py`.
   - HTTP/authentication selection: `tests\unit\test_mail_mcp_authentication.py`, `tests\contract\test_mail_service_configuration.py`, `tests\contract\test_wiki_openai_http_surface.py`, `tests\contract\test_oidc_http_lifecycle.py`.

   The extra factory-level security check blocked `McpConnection._connect` and confirmed the summary retrieval path; it did not require the failing grouped-read path.

6. No full-suite, live-network, model benchmark or deployment validation was performed. Suggested regression coverage under each task is future work, not a passing result from this review.

7. Branch report path and parent directories were checked for unsafe traversal/reparse points. The report did not previously exist. The original index comparison against `03db7dec19d64069abf9c64f5a9423ff0f348959` passed.

## Instructions for the implementation agent

1. Recheck the branch, source locations, dependency APIs and current behavior before editing. Line anchors describe this review snapshot.
2. Implement CR-001, CR-002 and CR-003 first; then follow task dependencies. Track progress here without erasing review evidence or user notes.
3. Preserve unrelated user work, including staged configuration and launcher changes. Do not reset, stash or overwrite them.
4. Keep domain logic framework-independent and integrations behind MCP. Preserve routing, alias enforcement, caller isolation, confirmation and connection lifecycle.
5. Add or update deterministic tests for every behavior changed, including factory/descriptor paths and cross-user credential refusal.
6. Run the smallest existing checks covering each change. Record actual commands, results and remaining limitations; never claim an unrun check passed.
