# Corporate Credit Analyst implementation

The `agents/credit` distribution owns `ai_agent_lab.credit`. `domain/models.py`
contains validated SEC business contracts; `application/ports/edgar.py` is the
replaceable discovery port; `application/skills/identification.py` owns
normalization, deduplication, analyst selection and confirmation. No framework,
MCP SDK or SEC HTTP client is imported into domain/application policy.

`infrastructure/mcp/client.py` adapts the official EdgarTools 6.3.0 JSON envelopes.
It verifies actual MCP schemas using the runtime JSON-schema validator, restricts
calls to company search and `include=[profile]`, checks nested errors and
attaches SEC provenance. Generic connections, configuration/manifests,
invocation context, permission/operation contracts and framework tool adaptation
come from public runtime/repository APIs. Concrete ports explicitly inherit
their Protocol. `bootstrap/composition.py` wires these components; the CLI has
structured and conversation paths. The small `maf/registered_agent.py` composes
native MAF from an injected registry and never imports a credit domain.

Configuration lives under `config/agents/credit`, `config/skills/credit` and
`config/mcp/edgartools.yaml`. The delivered capability is a read operation with
`credit:identify` permission. The registry refuses other implementations, write
operations or a different MCP allowlist. This is a local operator CLI, not an
HTTP authentication surface. Selected CIK membership is rechecked against a
fresh search; no retained application state or production persistence is needed.

Tests cover deterministic identity policy, wire errors, bounded retries,
permission-scoped native MAF tool invocation with a scripted model, configuration,
safe logs and repository architecture. The checked schema fixture was obtained
from the installed official server using MCP `list_tools`. No model or SEC
network is needed for reproducible tests. Install development dependencies with
the repository's dev environment and run:

```bash
python -m pytest tests/unit/credit tests/integration/credit tests/unit/test_install_runtime_source.py tests/architecture/test_distribution_boundaries.py
ruff check agents/credit agents/maf/src/ai_agent_lab/maf/registered_agent.py tests/unit/credit tests/integration/credit
mypy -p ai_agent_lab.credit -m ai_agent_lab.maf.registered_agent
```

For linked runtime source, configure `MYPYPATH` as described in the installer
module; built runtime wheels expose their public typing directly. Runtime 0.8.2
is below the new agent's declared minimum. Test network integration separately
using the [user guide](../users/credit-agent.md); never report a fake response as
a live SEC identification. Review the
[integration report](../../spec/implementation/issue-14/INTEGRATION.md) for the
actually tested versions and limitations.
