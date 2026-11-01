# Mail's shared native runtime integration

Mail still builds a normal MAF Agent in its composition root. Skills, prompts,
mailbox resolution, source ACLs, confirmation security floor, ledger, presenters
and result renderers remain in Mail.

`MailAgentSession` only injects these domain collaborators into the runtime's
`AgentFrameworkSession`. Native output translation and bounded streaming/
normal approval orchestration no longer live in this repository.
The old MAF streaming translator was removed; framework-level characterization
now belongs to the runtime binding tests.

HTTP uses shared `HttpConversationEngine`, `ConversationEntrypoint` and
`ManagedAgentWorker`. Existing `build_app` remains the local launch point, and
the CLI still uses its console resolver. Both retain ticket/command behavior;
this migration does not introduce native MAF suspended-run resume.
Mail explicitly requires verified email and keeps its existing discovery/auth
configuration, OpenAI surfaces, OIDC-over-demo-key precedence and safe MCP close.
The native export in `adapters/maf/native.py` also yields the normal Agent in an
async dependency scope. HTTP uses the optional advanced conversation composition
to attach Mail tickets, deterministic gates and renderers.

Mail composition lives in `bootstrap/`; the HTTP launch point is
`ai_agent_lab.mail.bootstrap.service:build_app`, and the native factory is
`ai_agent_lab.mail.adapters.maf.native:create_agent`. Only these current paths
are supported. The session adapter lives in
`adapters/maf/session.py` and deliberately references bootstrap's
`MailAgentRuntime`; inner application code does not depend on that adapter.
The generic `ai_agent_lab.maf` adapter remains a separate distribution.

Install from both source checkouts with the existing install workflow. MAF core
is deliberately aligned to `>=1.18,<1.19`, OpenAI adapter `>=1.14.2,<1.15`,
runtime agents and MAF integration `1.x`. Provider adapter versions are not the
core SDK version; no blind major upgrade was made.

One deployment per managed worker process. Conversation turns are serialized,
scopes drain on shutdown, cancelled/failed native state is retired, and changed
verified identity claims select new resources. Writes and confirmed ticket
execution still recheck deterministic domain authorization and stored arguments.
Memory state is single-instance and does not survive restart.

The runtime contract is a Python pilot. .NET/Java implementation/parity and any
production release exception require separate approval; this does not claim
cross-language adoption or a production sandbox. Native approval resume and
multi-replica durability/idempotency remain separate increments.

Migration validation: 192 targeted Mail/lab scenario, HTTP, domain-gate and
ticket tests passed; Ruff and strict mypy (82 Mail/MAF source files) passed.
The shared runtime pilot passed 234 targeted tests and strict typing on its
17 changed production files. Independent installed wheels and an isolated local
worker were exercised. Existing local latency budgets passed without inference.
