"""Correspondence between the logical mail tools and a deployed MCP server.

The skills and the agent only ever name a logical tool - ``search_mail`` - while
a deployed server exposes whatever names its authors chose. Keeping the two apart
is what allows the same agent to run against a Gmail server, an Exchange server
or a test double without touching a skill.

The binding is validated against the catalogue at load time, so a server that
does not cover the contract fails immediately instead of failing on the first
call the user makes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

from ai_agent_lab.infrastructure.config.directory import ConfigurationDirectory
from ai_agent_lab.mcp.mail.catalog import MailToolCatalog, MailToolName
from ai_agent_lab.mcp.mail.errors import MailToolProtocolError

MCP_DIRECTORY = "mcp"


class McpBindingError(MailToolProtocolError):
    """Raised when a delivered binding does not cover the tool contract."""


class McpToolBinding:
    """Resolves the remote name of a logical tool."""

    def __init__(self, server: str, tools: Mapping[str, str]) -> None:
        self._server = server
        self._tools = dict(tools)

    @property
    def server(self) -> str:
        """Name of the bound MCP server."""
        return self._server

    def remote_name(self, tool: MailToolName) -> str:
        """Return the name the deployed server exposes for a logical tool."""
        remote = self._tools.get(tool.value)
        if remote is None:
            raise McpBindingError(f"server {self._server!r} binds no tool for {tool.value!r}")
        return remote

    def as_mapping(self) -> Mapping[str, str]:
        """Return every binding, logical name to remote name."""
        return dict(self._tools)


class McpToolBindingLoader:
    """Reads and validates the binding delivered for a mail MCP server."""

    def __init__(self, directory: ConfigurationDirectory, catalog: MailToolCatalog) -> None:
        self._directory = directory
        self._catalog = catalog

    def load(self, name: str) -> McpToolBinding:
        """Read the binding of one server and check it covers every tool."""
        path = self._directory.require(MCP_DIRECTORY, f"{name}.yaml")
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise McpBindingError(f"could not read {path}: {error}") from error
        if not isinstance(document, dict):
            raise McpBindingError(f"{path} must contain a mapping")
        tools = self._tools(document, path)
        self._require_full_coverage(tools, path)
        return McpToolBinding(str(document.get("server", name)), tools)

    @staticmethod
    def _tools(document: dict[str, Any], path: object) -> dict[str, str]:
        """Return the declared correspondence, refusing a malformed one."""
        declared = document.get("tools")
        if not isinstance(declared, dict):
            raise McpBindingError(f"{path}: field 'tools' must be a mapping")
        invalid = [key for key, value in declared.items() if not isinstance(value, str) or not value.strip()]
        if invalid:
            raise McpBindingError(f"{path}: tools {sorted(invalid)} must map to non-empty names")
        return {str(key): str(value).strip() for key, value in declared.items()}

    def _require_full_coverage(self, tools: dict[str, str], path: object) -> None:
        """Refuse a binding that does not name every catalogued tool."""
        expected = {name.value for name in self._catalog.names()}
        missing = sorted(expected - set(tools))
        if missing:
            raise McpBindingError(f"{path}: no binding for {missing}")
        unknown = sorted(set(tools) - expected)
        if unknown:
            raise McpBindingError(f"{path}: unknown tools {unknown}")
