"""Application-owned loading policy for Mail MCP bindings."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.mcp.binding import McpServerBinding, McpServerBindingLoader
from ygo74.agent_runtime.domains.mcp.configuration import McpServerConfiguration, McpServerConfigurationLoader

from ai_agent_lab.mail.domain.operation_names import MailToolName
from ai_agent_lab.mail.infrastructure.configuration.environment import MailEnvironmentFile
from ai_agent_lab.mail.infrastructure.mcp.errors import McpBindingError

MCP_DIRECTORY = "mcp"


def _binding_path(directory: ConfigurationDirectory, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or ".." in name or name.endswith("."):
        raise McpBindingError(f"unsafe Mail MCP server configuration name {name!r}")
    path = directory.require(MCP_DIRECTORY, f"{name}.yaml").resolve()
    if not path.is_relative_to((directory.path / MCP_DIRECTORY).resolve()):
        raise McpBindingError(f"MCP server configuration {name!r} is outside config/mcp")
    return path


def load_binding(directory: ConfigurationDirectory, name: str) -> McpServerBinding[MailToolName]:
    """Load one Mail binding with the runtime parser and Mail error category.

    Args:
        directory: Application-selected root that contains the delivered MCP files.
        name: Binding filename without its ``.yaml`` suffix.
    """
    path = _binding_path(directory, name)
    loader = McpServerBindingLoader(MailToolName, error_factory=McpBindingError)
    return loader.load(path, name=name)


def load_configuration(
    directory: ConfigurationDirectory,
    name: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> McpServerConfiguration[MailToolName]:
    """Resolve YAML connection settings; only designated secrets come from the environment."""
    path = _binding_path(directory, name)
    if environment is None:
        MailEnvironmentFile().load()
    loader = McpServerConfigurationLoader(MailToolName, environment=environment, error_factory=McpBindingError)
    return loader.load(path, name=name)
