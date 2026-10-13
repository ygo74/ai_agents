"""Selection of the mail MCP implementation for the configured runtime mode."""

from __future__ import annotations

import logging
from pathlib import Path

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.mcp.binding import McpConnection, McpServerBinding
from ygo74.agent_runtime.domains.mcp.configuration import McpServerConfiguration
from ygo74.agent_runtime.domains.mcp.dialects import DialectRegistry

from ai_agent_lab.mail.application.ports.mail_tools import MailTools
from ai_agent_lab.mail.domain.operation_names import MailToolName
from ai_agent_lab.mail.infrastructure.configuration.settings import (
    MailAgentMode,
    MailAgentSettings,
)
from ai_agent_lab.mail.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.infrastructure.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mail.infrastructure.mcp.configuration import load_binding, load_configuration
from ai_agent_lab.mail.infrastructure.mcp.connection import MailMcpConnectionFactory
from ai_agent_lab.mail.infrastructure.mcp.dialects import create_dialect_registry
from ai_agent_lab.mail.infrastructure.mcp.errors import McpBindingError

_logger = logging.getLogger(__name__)


class MailToolsProvider:
    """Builds the mail MCP implementation the configuration asks for.

    The agent and the skills are identical in every mode; only the object built
    here changes. That is the property the runtime modes exist to prove.

    In ``mcp`` mode the provider also reports what the bound server can serve,
    so a capability no server offers is never advertised to the model.
    """

    def __init__(
        self,
        settings: MailAgentSettings,
        dataset_loader: MailDatasetLoader,
        *,
        owner_id: str | None = None,
        server: str | None = None,
        dialects: DialectRegistry[MailTools, [McpConnection, str]] | None = None,
    ) -> None:
        _logger.info("Initializing Mail tools provider")
        _logger.debug(
            "MailToolsProvider.__init__ arguments: mode=%s, owner_id=%s, "
            "server=%s, dialects_supplied=%s, dataset_loader_type=%s",
            settings.mode.value,
            owner_id or settings.user_id,
            server,
            dialects is not None,
            type(dataset_loader).__name__,
        )
        self._settings = settings
        self._dataset_loader = dataset_loader
        self._owner_id = owner_id or settings.user_id
        self._server = server
        self._dialects = dialects or create_dialect_registry()
        self._connection: McpConnection | None = None
        self._configuration: McpServerConfiguration[MailToolName] | None = None

    @staticmethod
    def server_for(manifest: AgentManifest) -> str:
        """Select the one mailbox backend declared by the agent's skills."""
        servers = {skill.mcp_server for skill in manifest.skills if skill.mcp_tools}
        if None in servers or not servers:
            raise McpBindingError("Mail MCP skills must declare mcp_server in skill.yaml")
        if len(servers) != 1:
            raise McpBindingError("Mail skills must share one MCP server; multiple mailbox backends are not supported")
        server = next(iter(servers))
        if server is None:
            raise McpBindingError("Mail MCP skills must declare mcp_server in skill.yaml")
        return server

    def build(self, *, base_path: Path | None = None) -> MailTools:
        """Return the mail tools matching the configured mode."""
        _logger.info("Building Mail tools backend")
        _logger.debug(
            "MailToolsProvider.build arguments: mode=%s, base_path=%s, owner_id=%s",
            self._settings.mode.value,
            base_path,
            self._owner_id,
        )
        if self._settings.mode is MailAgentMode.MOCK:
            return self._build_mock(base_path or Path.cwd())
        return self._build_mcp(base_path)

    def capabilities(self, *, base_path: Path | None = None) -> frozenset[MailToolName]:
        """Return the capabilities the configured backend can actually serve."""
        _logger.info("Resolving Mail backend capabilities")
        _logger.debug(
            "MailToolsProvider.capabilities arguments: mode=%s, base_path=%s",
            self._settings.mode.value,
            base_path,
        )
        if self._settings.mode is MailAgentMode.MOCK:
            capabilities = frozenset(MailToolName)
        else:
            capabilities = self._binding(base_path).capabilities
        _logger.debug(
            "Resolved Mail backend capabilities: count=%d, names=%s",
            len(capabilities),
            sorted(name.value for name in capabilities),
        )
        return capabilities

    async def aclose(self) -> None:
        """Close the MCP session, if one was opened."""
        _logger.info("Closing Mail tools provider")
        _logger.debug(
            "MailToolsProvider.aclose arguments: has_connection=%s",
            self._connection is not None,
        )
        if self._connection is None:
            return
        await self._connection.aclose()
        self._connection = None

    def _build_mock(self, base_path: Path) -> MailTools:
        """Build the mail tools backed by the configured dataset."""
        _logger.info("Building in-memory Mail tools backend")
        _logger.debug("MailToolsProvider._build_mock arguments: base_path=%s", base_path)
        dataset = self._settings.mock_dataset
        resolved = dataset if dataset.is_absolute() else base_path / dataset
        _logger.debug("Resolved Mail mock dataset path: %s", resolved)
        return InMemoryMailTools(self._dataset_loader.load_file(resolved))

    def _build_mcp(self, base_path: Path | None) -> MailTools:
        """Build the client of the bound mail MCP server."""
        _logger.info("Building MCP Mail tools backend")
        _logger.debug(
            "MailToolsProvider._build_mcp arguments: base_path=%s, server=%s, owner_id=%s",
            base_path,
            self._server,
            self._owner_id,
        )
        if not self._server:
            raise McpBindingError("Mail MCP mode requires a server declared by the skill manifests")
        self._configuration = load_configuration(ConfigurationDirectory.resolve(base_path=base_path), self._server)
        binding = self._configuration.binding
        self._connection = MailMcpConnectionFactory().build(self._configuration)
        tools = self._dialects.build(binding, self._connection, self._owner_id)
        _logger.debug(
            "Built MCP Mail tools backend: binding=%s, transport=%s, dialect=%s, tools_type=%s",
            binding.server,
            binding.transport.value,
            binding.dialect,
            type(tools).__name__,
        )
        return tools

    def _binding(self, base_path: Path | None) -> McpServerBinding[MailToolName]:
        """Load the delivered description of the bound server."""
        _logger.info("Loading Mail MCP server binding")
        _logger.debug(
            "MailToolsProvider._binding arguments: base_path=%s, server=%s",
            base_path,
            self._server,
        )
        if self._configuration is not None:
            return self._configuration.binding
        if not self._server:
            raise McpBindingError("Mail MCP mode requires a server declared by the skill manifests")
        directory = ConfigurationDirectory.resolve(base_path=base_path)
        return load_binding(directory, self._server)
