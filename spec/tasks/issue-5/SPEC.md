# Specification

## Issue

`ygo74/ai_agents` issue #5, “Finlaize core migration to ai-enterprise-agent-runtime”.

## Objective

Complete the migration of every remaining class in the `ai-agent-lab-core`
distribution to `ai-enterprise-agent-runtime`, except for the classes in
`config/azure_credentials.py` and `config/chat.py`. The current Mail and Wiki
agents will consume migrated foundations through the runtime's public Python
imports. Developers should be able to focus on their agents' functional
behavior rather than recreating shared technical layers.

## Context

This issue spans two Git repositories:

- **Primary repository and issue tracker:** `ai_agents`, which contains the
  current agents, consumers, and two explicitly excluded modules.
- **Secondary repository and migration target:**
  `ai-enterprise-agent-runtime`, which provides the Python distributions
  `ygo74-agent-runtime-security` and `ygo74-agent-runtime-agents`, including
  `configuration`, `contracts`, and `security` domains.

The runtime already owns the conversation and manifest value models,
authenticated identity, permissions, user context, untrusted-content contracts,
sessions, and human approval. The remaining classes in `ai_agent_lab.core` are
still used by the agents or their tests.

The requester confirmed that these remaining classes can move, that the current
agents should adopt the runtime's new import paths, that there are no other
clients to preserve, and that this change is Python-only. The YAML manifest
structures are intended to be fixed library contracts.

## Problem

Developers adding an agent still need a laboratory-specific distribution for
configuration discovery and loading, construction of the runtime user context,
and the framework-neutral reasoning port. These shared technical capabilities
belong in the reusable runtime so each agent repository does not need to
recreate them.

## Scope

Move the following classes from
`agents/core/src/ai_agent_lab/core/` into public Python modules in the runtime:

| Source | Types | Target domain |
|---|---|---|
| `errors.py` | `DomainError`, `DomainValidationError` | A single common Python runtime error module |
| `config/directory.py` | `ConfigurationNotFoundError`, `ConfigurationDirectory` | `domains/configuration` |
| `config/environment.py` | `EnvironmentFile`, `ENV_FILE` | `domains/configuration` |
| `config/manifests.py` | `ConfigurationError`, `YamlDocument`, `YamlSection`, `SkillManifestLoader`, `AgentManifestLoader` | `domains/configuration`, reusing runtime contracts and security types |
| `reasoning/errors.py` | `ReasoningError`, `ReasoningUnavailableError`, `ReasoningOutputError` | A Python reasoning domain |
| `reasoning/ports.py` | `ReasoningOutputT`, `TextReasoner` | The Python reasoning domain; use existing `ReasoningRequest` and `UntrustedSection` types |
| `security/user_contexts.py` | `UserContextFactory` | `domains/security`, reusing `AgentPrincipal`, `Permission`, and `UserContext` |

Also provide versioned JSON Schema Draft 2020-12 resources for the YAML files
`agent.yaml` and `skill.yaml`. These schemas are the structural contract for
the delivered YAML. Their fields and constraints are:

- `agent.yaml` requires `name` and `description` as non-empty strings and
  `skills` as a non-empty sequence of non-empty strings. No other top-level
  fields are accepted.
- `skill.yaml` requires non-empty string fields `tool_name`, `implementation`,
  and `description`, plus an `operation` object. `operation` requires `type`
  (`READ` or `WRITE`), `risk` (`LOW`, `MEDIUM`, or `HIGH`), a non-empty
  `permission` string, and boolean `confirmation_required`. `mcp_tools` is an
  optional sequence of non-empty strings and defaults to an empty sequence.
  No other top-level or `operation` fields are accepted.
- `AGENT.md` and `SKILL.md` remain separate Markdown files; the manifest schemas
  do not attempt to validate their prose.
- The loader continues semantic checks that a static schema cannot express:
  the permission must exist in the application's registry and the operation
  must satisfy its configured security floor.

The runtime becomes the sole owner of the migrated implementations. Update all
production and test imports in the current agents to the runtime's public
modules. Do not keep compatibility aliases or duplicate implementations under
`ai_agent_lab.core`. Keep `ai-agent-lab-core` only for the two excluded modules.

Preserve the current observable behavior for configuration discovery, YAML
parsing and validation, declared skill order, security-floor enforcement,
`.env` precedence, immutable permission construction, and the asynchronous
typed `TextReasoner` contract.

## Out of scope

- Migrating `config/azure_credentials.py` or the types in `config/chat.py`.
- Migrating Microsoft Agent Framework, LangChain/LangGraph, or agent business
  capabilities.
- Migrating the remaining MCP plumbing in `ai_agents`; that is a separate
  migration batch.
- Adding .NET or Java implementations of these Python APIs.
- Moving application-owned decisions about which permissions a user receives.

## Expected behavior

1. Migrated classes are importable from public runtime modules and all runtime
   dependencies they need are explicitly declared by the supplying
   distribution.
2. Loaders use the runtime's existing `AgentManifest`, `SkillManifest`,
   `AgentPrincipal`, `Permission`, `UserContext`, `ReasoningRequest`, and
   `UntrustedSection` types; they do not define copies.
3. Configuration loading rejects malformed YAML, missing or incorrectly typed
   fields, unknown manifest fields, unknown permissions, and operations below
   the security floor with clear errors.
4. The process environment continues to take precedence over values loaded
   from `.env`. `UserContextFactory` receives permissions from the application
   and does not infer a role policy.
5. `TextReasoner` stays independent of agent frameworks. Its implementations
   remain in the `ai_agents` adapters.
6. The configuration override is renamed to the neutral runtime-specific
   `YGO74_AGENT_RUNTIME_CONFIG_DIR`. Mail, Wiki, their tests, images, and
   documentation use this name. There is no fallback for
   `AI_AGENT_LAB_CONFIG_DIR` because there are no other clients to preserve.
7. Python-only support and its parity status are documented in the runtime;
   documentation must not imply that .NET or Java exposes these APIs.

## Architecture

- Add configuration and security APIs to their existing Python runtime
  domains, and add a Python reasoning domain if no existing module is suitable.
  Place common errors in one canonical module without creating circular
  dependencies between distributions.
- Use typed configuration models as the structural source of truth. Publish
  their JSON Schema Draft 2020-12 representations as versioned runtime
  resources, document stable schema identifiers and associate them with the
  corresponding YAML files. Runtime loading must validate against the same
  structural constraints, while retaining the dynamic permission and security
  floor checks.
- Declare dotenv and YAML dependencies explicitly under the runtime's
  distribution/extra model. Importing configuration, security, or reasoning
  must not load FastAPI, the MCP SDK, or an agent framework as a side effect.
- In `ai_agents`, update all production and test imports, trim the core
  distribution dependencies, update architecture rules, and revise relevant
  developer and deployment documentation.
- Keep the repositories' Git histories and branches independent. Each change,
  dependency update, documentation change, and test belongs to its own
  repository.

## Constraints

- Follow the Python version, strict typing, typed-package, and dependency
  conventions declared by the runtime.
- The runtime's security errors have their own hierarchy. Moving `DomainError`
  must not hide or reclassify security refusals; application boundaries must
  continue to handle them explicitly.
- Preserve the existing local changes in `ai_agents`; only issue-related
  changes may be included in the issue branch and commits.
- This change exposes Python APIs only. Record their Python-only status in the
  runtime's parity documentation; do not claim .NET or Java support.
- The manifest YAML structure is intentionally fixed. Future changes to it are
  versioned and documented contract changes.

## Acceptance criteria

1. Every class in the scope table is implemented in the runtime. The two
   excluded modules remain in `ai_agents`.
2. Every current `ai_agents` consumer uses runtime public import paths. The
   core distribution contains no definition or compatibility re-export of the
   migrated types.
3. Loaded manifests produce the existing runtime models and preserve skill
   order, permission resolution, and security-floor enforcement.
4. The published agent and skill schemas describe the fixed structures above,
   are shipped and documented by the runtime, and validate all delivered YAML
   manifests.
5. `.env` loading, directory discovery, `UserContextFactory`, and the
   framework-neutral reasoning contract preserve the guarantees in this SPEC.
6. Runtime dependencies are explicit and minimal. Importing the migrated
   domains does not import FastAPI or MCP unless the consumer requests those
   capabilities.
7. Mail and Wiki agents, deployment images, tests, and documentation use
   `YGO74_AGENT_RUNTIME_CONFIG_DIR` and the new runtime import paths; no legacy
   variable fallback or migrated import shim remains.
8. Relevant tests and quality checks pass in both repositories, and their
   architecture rules and documentation no longer assign migrated classes to
   `ai_agent_lab.core`.
9. Manifest-loading performance regresses by no more than 10% against the
   pre-migration baseline on the same configuration fixture. The migration adds
   no work to the request execution path.

## Test strategy

- Use current `ai_agents` tests as the behavioral reference for errors,
  directory discovery, `.env`, manifests, user context, and reasoning.
- Add runtime tests for public imports, manifest parsing, schema compliance,
  invalid examples, dynamic permission/security-floor checks, and package
  boundaries. Confirm imports do not load FastAPI or MCP unnecessarily.
- Validate all delivered `agent.yaml` and `skill.yaml` files against the
  published schemas. Check that structural validation and the runtime loader
  remain aligned.
- Validate updated consumers and distribution boundaries in `ai_agents`, then
  run the relevant documented quality checks in both repositories.
- Measure manifest loading before and after against the same local fixtures.
  Tests must not require an LLM provider, external service, or real credentials.

## Risks

- Removing old import paths requires every current agent consumer and test to
  move in the same change; no historical aliases are to remain.
- A shared error base can affect exception handling. Security refusals must
  remain explicitly distinguished at application boundaries.
- Published schemas freeze the manifest shape; future evolution needs a
  versioned and documented contract change.
- `ai_agents` already has unrelated local changes. They must be preserved and
  kept out of this issue's branch and commits.

## Open questions

None. The requester confirmed the target repository, migration scope, neutral
environment variable name, agent import updates, lack of other clients,
Python-only support, and fixed YAML manifest structures with published
validation schemas.
