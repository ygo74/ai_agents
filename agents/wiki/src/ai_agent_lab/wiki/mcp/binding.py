"""Wiki configuration policies around the runtime's generic MCP binding."""

from __future__ import annotations

from collections.abc import Mapping

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.mcp.binding import (
    McpServerBinding as McpServerBinding,
)
from ygo74.agent_runtime.domains.mcp.binding import (
    McpServerBindingLoader as RuntimeMcpServerBindingLoader,
)
from ygo74.agent_runtime.domains.mcp.binding import McpTransport as McpTransport

from ai_agent_lab.wiki.catalog import WikiToolCatalog, WikiToolName
from ai_agent_lab.wiki.wiki_errors import WikiToolProtocolError, WikiToolUnavailableError

MCP_DIRECTORY = "mcp"
_WRITABLE = frozenset({"0", "false", "no", "off"})


class McpBindingError(WikiToolProtocolError):
    """A delivered wiki MCP binding cannot be used as declared."""


class McpServerBindingLoader:
    """Resolve the Wiki configuration directory, then delegate validation."""

    def __init__(self, directory: ConfigurationDirectory) -> None:
        self._directory = directory
        self._loader = RuntimeMcpServerBindingLoader(WikiToolName, error_factory=McpBindingError)

    def load(self, name: str) -> McpServerBinding[WikiToolName]:
        """Load one binding using the shared runtime parser and validator."""
        path = self._directory.require(MCP_DIRECTORY, f"{name}.yaml")
        binding = self._loader.load(path, name=name)
        binding.require_declared_capabilities()
        return binding


def is_read_only(value: str) -> bool:
    """Treat absent or unrecognised deployment values as read-only."""
    return value.strip().casefold() not in _WRITABLE


def capabilities_in(
    binding: McpServerBinding[WikiToolName],
    environment: Mapping[str, str],
) -> frozenset[WikiToolName]:
    """Apply the Wiki deployment's read-only policy to declared capabilities."""
    variable = binding.read_only_variable
    if not variable or not is_read_only(environment.get(variable, "")):
        return binding.capabilities
    catalog = WikiToolCatalog()
    return frozenset(capability for capability in binding.capabilities if not catalog.descriptor(capability).is_write)


def with_resolved_stdio_environment(
    binding: McpServerBinding[WikiToolName],
    environment: Mapping[str, str],
) -> McpServerBinding[WikiToolName]:
    """Resolve Wiki's source-variable references before handing the binding to the runtime."""
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
