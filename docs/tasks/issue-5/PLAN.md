# Implementation Plan

## Issue

#5 — Finalize core migration to `ai-enterprise-agent-runtime`

## Specification

[`./SPEC.md`](./SPEC.md)

## Objective

Move the remaining reusable Python foundations from `ai_agents` to
`ai-enterprise-agent-runtime`, publish fixed JSON Schemas for agent and skill
YAML manifests, and update the current agents to use the runtime APIs and
configuration variable.

## Preconditions

- The SPEC has been approved.
- After this PLAN is approved, prepare independent branches in both Git
  repositories from their latest `origin/main`:
  - `ai_agents`: `refactor/5-finish-core-migration`
  - `ai-enterprise-agent-runtime`: `refactor/5-finish-core-migration`
- The current `ai_agents` checkout has unrelated local modifications. Preserve
  it untouched and use an isolated worktree from the updated `origin/main` for
  this issue. Carry only `docs/tasks/issue-5/SPEC.md` and `PLAN.md` into that
  worktree. Create an independent worktree for the runtime repository as well;
  its current feature branch is not the base for this work.
- Fetch and verify each remote `main` before creating the worktrees. Do not
  implement on either current feature branch or on `main`.
- Pre-migration performance baseline: the delivered Mail agent manifest loaded
  in a median of **37.538 ms per load**, measured in the isolated Python 3.12
  issue environment over five samples of twenty loads. Reuse this Mail fixture
  and environment after migration.
- Keep the migration Python-only, as approved. Record this explicit parity
  exception in the runtime's parity documentation.

## Steps

### Step 1 — Prepare isolated issue branches

**Objective:** Create clean work areas from the latest upstream `main` in both
repositories without disturbing existing local work.

**Files/components:** Git metadata for `/data/repos/ai_agents` and
`/data/repos/ai-enterprise-agent-runtime`; issue SPEC and PLAN documents.

**Modifications:** Fetch each remote, verify `main` is synchronized with
`origin/main`, create the two named branches/worktrees, and copy only the issue
SPEC and PLAN into the `ai_agents` issue worktree. Keep the original dirty
checkout unchanged.

**Validation:** Confirm each worktree is on its new branch at the latest
`origin/main` commit, and inspect both working trees before implementation.

### Step 2 — Move shared error and user-context foundations

**Objective:** Establish the runtime-owned error base and user-context factory
before moving classes that depend on them.

**Files/components:** In `ai-enterprise-agent-runtime`, add a typed
`domains/errors/` package (owned by the security distribution) and add
`domains/security/user_context_factory.py`. In `ai_agents`, update
`azure_credentials.py` to import `DomainError` from the runtime while leaving
the Azure credential provider and chat enums in core.

**Modifications:** Move `DomainError` and `DomainValidationError` with their
existing semantics. Include the errors package's `py.typed` marker in the
security wheel. Move `UserContextFactory`, using existing `AgentPrincipal`,
`Permission`, and `UserContext` types. Keep `SecurityError` and its subclasses
distinct; audit current exception-rendering boundaries to ensure security
refusals remain explicitly caught.

**Validation:** First add runtime unit tests for the moved exceptions and
factory, including immutable permission construction and user/session
attribution. Run focused runtime tests and strict typing for the affected
packages.

### Step 3 — Move configuration loading and publish manifest schemas

**Objective:** Make configuration discovery, `.env` loading, and manifest
loading reusable runtime APIs with a fixed, documented YAML contract.

**Files/components:** In `ai-enterprise-agent-runtime`, extend
`packages/python/agents/.../domains/configuration/`, add typed manifest-input
models and loader modules, package the two JSON Schema resources, and update the
agents distribution's `pyproject.toml`, package data, CI, tests, and Python
documentation.

**Modifications:** Move `ConfigurationDirectory`, `EnvironmentFile`, YAML
reading and section types, `SkillManifestLoader`, and `AgentManifestLoader`.
Use typed input models as the structural source for the published Draft
2020-12 schemas. The loader validates against those same constraints, then
performs dynamic permission resolution and security-floor enforcement using
the existing runtime models. Add the `configuration` extra for the dotenv and
YAML dependencies so consumers install these capabilities explicitly without
pulling in the MCP or HTTP stack.

Publish `agent.yaml` and `skill.yaml` schemas as package resources, document
their stable identifiers and usage, and validate the delivered examples. Keep
`AGENT.md` and `SKILL.md` as separate Markdown inputs.

**Validation:** First add tests for valid and invalid manifests, schema
packaging, exact field sets, enum values, permission resolution, security-floor
checks, directory lookup, and `.env` precedence. Run focused runtime tests,
package build checks, Ruff, and public-import/optional-dependency tests.

### Step 4 — Move the reasoning port and errors

**Objective:** Provide a framework-neutral reasoning contract from the runtime.

**Files/components:** Add `domains/reasoning/` to the runtime agents
distribution with `ports.py`, `errors.py`, and its typing marker; update
package data and runtime tests. Migrate callers and tests in `ai_agents` to the
new public imports.

**Modifications:** Move `TextReasoner`, `ReasoningOutputT`, and the reasoning
error hierarchy. Import `ReasoningRequest` and `UntrustedSection` from their
existing runtime security module. Keep MAF and LangGraph implementations in
their adapters. Preserve the current async signature and typed Pydantic output.

**Validation:** First add tests for protocol shape, type-checking, error
inheritance, and runtime imports without either agentic framework installed.
Run focused runtime and consumer tests and strict typing.

### Step 5 — Rewire `ai_agents` consumers and remove migrated core code

**Objective:** Make the current agents use only runtime-owned APIs for the
migrated technical layers.

**Files/components:** Update production imports and tests across `agents/` and
`tests/`; revise `agents/core/pyproject.toml`, Mail/Wiki distribution
dependencies, `scripts/install.py` if needed, root mypy/source configuration,
and `tests/architecture/test_distribution_boundaries.py`.

**Modifications:** Replace imports of moved core classes with runtime module
paths, remove their source definitions and obsolete core package dependencies,
and add direct runtime distribution dependencies where agent code imports those
APIs. Retain `chat.py` and `azure_credentials.py` in core. Update the
architecture rules to permit only the intended runtime domain imports and keep
transport/framework boundaries enforced.

Rename `AI_AGENT_LAB_CONFIG_DIR` to `YGO74_AGENT_RUNTIME_CONFIG_DIR` in the
runtime API and all Mail/Wiki code, test fixtures, deployment images, and docs.
Do not retain the old variable or old import aliases.

Update the developer guide, repository structure, configuration guide, agent
guides, deployment docs, and examples that describe the source of the migrated
APIs. Remove obsolete references to the deliberate-retention decision in
`runtime-extraction-candidates.md` and `architecture.md`, and describe the
remaining two core modules accurately.

**Validation:** First add/update architecture and behavior tests for runtime
imports, package dependency boundaries, the new environment variable, and
manifest loading through the runtime. Run focused tests, then the full relevant
`ai_agents` pytest, Ruff, and mypy checks.

### Step 6 — Cross-repository validation and review

**Objective:** Verify both deliverables together and prepare reviewable changes.

**Files/components:** Both issue branches, their package builds, CI workflows,
documentation, and task SPEC/PLAN.

**Modifications:** Reconcile any integration issues without changing the
approved scope. Record the Python-only parity status in the runtime. Review both
repository diffs independently and ensure only issue files are included. The
runtime PR is the dependency of the `ai_agents` PR. Keep the runtime checkout
linked locally for downstream validation. Do not publish a package release as
part of this issue; the `ai_agents` workflow currently installs runtime wheels
from PyPI, so its remote CI may require a separately approved runtime release
before it can pass against the new API.

**Validation:** Run the runtime's Python tests, Ruff, and package build/metadata
checks. Run `ai_agents`' full documented tests, Ruff, and mypy checks against
the issue runtime checkout. Compare manifest-loading performance on the same
fixtures before and after; require no more than a 10% regression. Run
`git diff --check` and inspect both final diffs for unexpected files or secrets.

## Tests

- **Runtime security:** common error types, `UserContextFactory`, imports, and
  exception-boundary behavior.
- **Runtime configuration:** YAML input model and schema agreement; valid and
  invalid agent/skill manifests; safe parsing; directory and `.env` behavior;
  dynamic permission and floor checks; package resource inclusion.
- **Runtime reasoning:** protocol signature, typed outputs, error behavior, and
  independence from MAF/LangChain.
- **Runtime package quality:** Ruff, pytest, strict typing where configured,
  wheel build and metadata checks, and no accidental FastAPI/MCP imports.
- **Agent consumers:** full pytest suite, architecture/distribution boundaries,
  Ruff, mypy, configuration variable references, and Mail/Wiki dependency
  installs from the runtime checkout.

## Final validation

- Both repositories have clean, issue-scoped diffs on branches based on their
  latest `origin/main`.
- Runtime Python packages build and all relevant runtime checks pass.
- Current agents import the migrated APIs from the runtime and all relevant
  `ai_agents` checks pass.
- Both JSON Schemas are included in the runtime distribution and validate the
  delivered agent and skill YAML files.
- The environment variable and documentation use
  `YGO74_AGENT_RUNTIME_CONFIG_DIR` consistently.
- Manifest-loading performance remains within the SPEC's 10% regression
  budget.
- The original dirty `ai_agents` checkout remains unchanged.

## Risks

- Error-base movement may change what broad exception handlers catch; preserve
  explicit handling of runtime security errors.
- Fixed schemas make manifest shape changes versioned contract changes.
- New runtime APIs must be installed from the issue checkout while validating
  consumers; stale published wheels could hide missing imports.
- The existing `ai_agents` working tree contains unrelated modifications and
  must not be used as the implementation worktree.
- The `ai_agents` remote quality workflow resolves runtime packages from PyPI,
  whereas local integration uses `--runtime-source`. Until the runtime API is
  available in a published wheel, remote CI for the dependent changes may not
  validate the same code that local integration tested.

## Technical decisions

- **Configuration environment variable:** use `YGO74_AGENT_RUNTIME_CONFIG_DIR`;
  do not retain the lab-specific alias because there are no other clients.
- **Import compatibility:** migrate every current agent and test; provide no
  old-path aliases or re-exports.
- **Manifest schema source:** typed Pydantic input models define the fixed YAML
  structure and generate the versioned JSON Schema resources. Permission
  existence and security-floor rules remain dynamic runtime checks.
- **Python-only API:** no .NET or Java implementation in this issue; record the
  explicitly approved parity exception in the runtime status documentation.
- **Error hierarchy:** keep runtime `SecurityError` separate from the moved
  common `DomainError`; preserve explicit catches at application boundaries.
- **Performance:** no request-path work is added; configuration load time may
  regress by at most 10% against the same pre-migration fixture baseline.

## Success criteria

- All in-scope classes have one implementation in the runtime; only the two
  excluded modules remain in `ai-agent-lab-core`.
- Mail and Wiki use the runtime API paths and new configuration variable.
- The schemas, runtime loaders, security checks, package boundaries, and docs
  agree with the approved SPEC.
- Relevant validation passes independently in both repositories, and the
  unrelated local work is preserved.
