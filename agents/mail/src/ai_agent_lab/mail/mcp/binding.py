"""Mail configuration adapter for the runtime's generic MCP bindings."""

from __future__ import annotations

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.mcp.binding import (
    McpServerBinding as McpServerBinding,
)
from ygo74.agent_runtime.domains.mcp.binding import (
    McpServerBindingLoader as RuntimeMcpServerBindingLoader,
)
from ygo74.agent_runtime.domains.mcp.binding import McpTransport as McpTransport

from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.mail_errors import MailToolProtocolError

MCP_DIRECTORY = "mcp"


class McpBindingError(MailToolProtocolError):
    """A delivered mail MCP binding cannot be used as declared."""


class McpServerBindingLoader:
    """Resolve the Mail configuration directory, then delegate validation."""

    def __init__(self, directory: ConfigurationDirectory) -> None:
        self._directory = directory
        self._loader = RuntimeMcpServerBindingLoader(MailToolName, error_factory=McpBindingError)

    def load(self, name: str) -> McpServerBinding[MailToolName]:
        """Load one binding using the shared runtime parser and validator."""
        path = self._directory.require(MCP_DIRECTORY, f"{name}.yaml")
        return self._loader.load(path, name=name)
