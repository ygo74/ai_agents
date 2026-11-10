# Common architecture for AI Agent Lab agents

Load this reference when planning a new agent, a stateful capability such as
user memory, an agent orchestrator, or a change shared across agents. It defines
the common structure. The Python Solution Architect reference adds current
Mail/Wiki ownership and framework constraints.

## Architecture boundary

Use Clean Architecture / Onion Architecture. Dependencies point inward:

```text
framework, transport, persistence, and MCP adapters
                    ↓
         application ports and use cases
                    ↓
              domain policy
```

The domain contains business models, rules, and invariants. The application
contains skills/use cases, deterministic orchestration, and ports required by
those use cases. Infrastructure implements storage and MCP-facing contracts.
Framework, CLI, and HTTP adapters translate at the edge. Bootstrap loads
configuration, constructs concrete adapters, injects them, and starts the
selected host. Domain and application code do not import framework, transport,
database, MCP SDK, or vendor API packages.

## Common agent layout

New agents use the same logical layers and package directories. Optional areas
are omitted when an agent does not need them; framework-specific code is the
intended point of variation.

```text
agents/<agent>/src/ai_agent_lab/<agent>/
  domain/                 models, value objects, enums, policies, domain errors
  application/
    ports/                Protocols required by use cases
    skills/                agent use cases and deterministic capability logic
    services/              application orchestration when a skill needs it
  infrastructure/
    configuration/        validated settings and provider configuration
    mcp/                   MCP bindings, dialects, and external tool adapters
    persistence/
      inmemory/            development and deterministic test adapters
      postgres/ or redis/  production adapter, when retained state needs it
  adapters/
    capabilities/          bind application skills to runtime descriptors
    <framework>/           framework-specific tool/session/result mapping
    cli/                   optional local user interface
    http/                  optional application-owned HTTP composition
  bootstrap/                composition roots and service factories

tests/
  unit/<agent>/             domain and application tests with injected fakes
  integration/<agent>/      adapters, persistence, and framework contracts
  security/<agent>/         identity, authorization, isolation, and data handling
  scenarios/<agent>/        reproducible multi-turn or cross-agent behavior
```

Do not create empty placeholder directories or layers that only forward calls.
Keep tests and framework distributions isolated in the repository's existing
packaging model. Mail and Wiki have historical layout differences; new agents
and new modules should follow this target. A broad move of existing files is a
separately scoped migration, not incidental cleanup during another feature.

## Ports, dependency injection, and framework adapters

- Define a focused Python `Protocol` for an external or replaceable dependency
  at the layer that needs it. Inject implementations into constructors and
  assemble them in bootstrap. Avoid service locators, module globals, and
  hidden construction inside a skill.
- Every concrete class implementing a `Protocol` explicitly subclasses it,
  such as `class RedisMemoryStore(UserMemoryStore):`. Type checking should
  verify the method signatures; a structurally compatible but undeclared class
  is not the repository convention.
- Reuse `ai-enterprise-agent-runtime` contracts for identity, authorization,
  operation risk, confirmations, manifests, conversation, output, and MCP
  mechanics. Do not copy those types or create parallel public contracts.
- Keep skill/use-case behavior framework-independent. A framework adapter
  converts the shared capability descriptor and session/result contract to
  public framework APIs. Mail's Microsoft Agent Framework adapter and Wiki's
  LangChain/LangGraph adapter remain separate. A new framework changes the
  adapter and composition, not the agent's domain rules or skill behavior.
- Keep agent distributions isolated so an agent does not acquire another
  agent's framework or import its private modules. Extract a shared component
  only after at least two agents need the same behavior and the shared owner is
  clear; generic technical contracts belong in the runtime.

## Retained state and production scaling

For application-owned state retained beyond one operation, define a storage
`Protocol` and provide:

1. an in-memory implementation for local development and deterministic tests;
2. a PostgreSQL or Redis implementation for production, selected by validated
   configuration and chosen for the data's transaction, query, durability, and
   latency needs.

Choose the backend in bootstrap from validated configuration; do not branch on
environment or instantiate a backend inside application skills. Define user
and tenant partitioning, concurrent updates, expiry/retention, deletion,
recovery, migrations, and secret handling with the data contract. Production
services must not silently fall back to process-local state.

This rule is for state owned by the application, including user memory,
confirmation tickets, or conversation data when the product requires
continuity. An in-memory fake for a remote Mail/Wiki/Jira system is a test or
demo adapter, not the production system of record; production access to those
systems remains behind their MCP contracts. A deliberately process-local cache
must have a stated capacity, expiry, and deployment limitation.

## Shape of the planned agent family

- **Mail** owns mail-specific models, operation policy, skills, and mailbox
  ports. Its agent framework and Gmail/Mail MCP dialects are adapters.
- **Wiki** owns page/search models, retrieval and write policy, skills, and
  confirmation meaning. Its LangChain/LangGraph integration is an adapter.
- **Jira/ticket agent** owns ticket vocabulary, workflow rules, and ticket use
  cases. Jira access and credentials stay behind an injected MCP port.
- **User-memory agent** owns memory capture, retrieval, correction, and
  deletion behavior. Its user-scoped state uses the retained-state pattern
  above; retrieved memories remain data, never trusted instructions.
- **Orchestrator agent** owns task decomposition, agent selection, and result
  aggregation. Depend on an injected typed agent-invocation port/registry and
  public agent contracts; do not import other agents' framework sessions,
  skills, or implementation packages. Apply authorization, timeouts, bounded
  concurrency, partial-failure behavior, and trace correlation explicitly.

These are ownership boundaries, not a mandate to implement all agents or to
choose one framework for the whole repository. A new agent's SPEC decides its
business behavior, data contract, and framework; its architecture still follows
the common layers above.

## Documentation expectations

Document every class and method so a developer can understand its purpose and
arguments. Use Python docstrings for Python code and the repository's standard
documentation form for other languages. In every non-trivial method, include
concise comments in the method body that explain the algorithm's stages,
ordering, and important invariants. Avoid comments that merely paraphrase
individual statements. Keep agent-specific details in the agent's own
references rather than adding agent names or domain policies to the shared
runtime.
