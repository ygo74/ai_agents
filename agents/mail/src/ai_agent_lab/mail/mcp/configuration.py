"""Application-owned loading policy for Mail MCP bindings."""

from __future__ import annotations

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.mcp.binding import McpServerBinding, McpServerBindingLoader

from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.mcp.errors import McpBindingError

MCP_DIRECTORY = "mcp"


def load_binding(directory: ConfigurationDirectory, name: str) -> McpServerBinding[MailToolName]:
    """Load one Mail binding with the runtime parser and Mail error category.

    Args:
        directory: Application-selected root that contains the delivered MCP files.
        name: Binding filename without its ``.yaml`` suffix.
    """
    path = directory.require(MCP_DIRECTORY, f"{name}.yaml")
    loader = McpServerBindingLoader(MailToolName, error_factory=McpBindingError)
    return loader.load(path, name=name)
