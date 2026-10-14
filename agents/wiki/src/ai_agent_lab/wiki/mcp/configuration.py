"""Wiki-specific policy applied around generic MCP bindings."""

from __future__ import annotations

from collections.abc import Mapping

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.mcp.binding import McpServerBinding, McpServerBindingLoader, McpTransport

from ai_agent_lab.wiki.catalog import WikiToolCatalog, WikiToolName
from ai_agent_lab.wiki.mcp.errors import McpBindingError
from ai_agent_lab.wiki.wiki_errors import WikiToolUnavailableError

MCP_DIRECTORY = "mcp"
_WRITABLE = frozenset({"0", "false", "no", "off"})


def load_binding(directory: ConfigurationDirectory, name: str) -> McpServerBinding[WikiToolName]:
    """Load one Wiki binding with the runtime parser and Wiki error category.

    Args:
        directory: Application-selected root that contains the delivered MCP files.
        name: Binding filename without its ``.yaml`` suffix.
    """
    path = directory.require(MCP_DIRECTORY, f"{name}.yaml")
    loader = McpServerBindingLoader(WikiToolName, error_factory=McpBindingError)
    binding = loader.load(path, name=name)
    binding.require_declared_capabilities()
    return binding


def is_read_only(value: str) -> bool:
    """Treat absent or unrecognised deployment values as read-only.

    Args:
        value: Raw value of the deployment's read-only environment variable.
    """
    return value.strip().casefold() not in _WRITABLE


def capabilities_in(
    binding: McpServerBinding[WikiToolName],
    environment: Mapping[str, str],
) -> frozenset[WikiToolName]:
    """Apply the Wiki deployment's read-only policy to declared capabilities.

    Args:
        binding: Validated server capabilities and transport configuration.
        environment: Environment values used to evaluate the deployment policy.
    """
    variable = binding.read_only_variable
    if not variable or not is_read_only(environment.get(variable, "")):
        return binding.capabilities
    catalog = WikiToolCatalog()
    return frozenset(capability for capability in binding.capabilities if not catalog.descriptor(capability).is_write)


def with_resolved_stdio_environment(
    binding: McpServerBinding[WikiToolName],
    environment: Mapping[str, str],
) -> McpServerBinding[WikiToolName]:
    """Resolve Wiki source-variable references before passing a binding to the runtime.

    Args:
        binding: Validated Wiki server binding containing environment references.
        environment: Runtime environment from which configured values are read.

    Raises:
        WikiToolUnavailableError: A referenced environment value is missing.
    """
    if binding.transport is not McpTransport.STDIO or not binding.env:
        return binding

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for target, source in binding.env.items():
        variable = source or target
        value = environment.get(variable)
        if value is None:
            missing.append(variable)
            continue
        resolved[target] = value

    if missing:
        raise WikiToolUnavailableError(
            f"wiki MCP server {binding.server!r} needs environment variable(s) {sorted(missing)}"
        )

    return McpServerBinding(
        server=binding.server,
        transport=binding.transport,
        capabilities=binding.capabilities,
        tools={alias: binding.remote(alias) for alias in binding.tools},
        dialect=binding.dialect,
        url=binding.url,
        command=binding.command,
        args=binding.args,
        env=resolved,
        read_only_variable=binding.read_only_variable,
        error_factory=McpBindingError,
    )
