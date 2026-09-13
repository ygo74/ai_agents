"""Selection of the mail MCP implementation for the configured runtime mode."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import (
    MailAgentMode,
    MailAgentSettings,
    MailMcpSettings,
)
from ai_agent_lab.mail.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mail.mcp.binding import McpServerBinding, McpServerBindingLoader, McpTransport
from ai_agent_lab.mail.mcp.connection import McpConnection
from ai_agent_lab.mail.mcp.dialects import MailDialectRegistry
from ai_agent_lab.mail.mcp.oauth import MailOAuthProvider
from ai_agent_lab.mail.tools_port import MailTools

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
        mcp_settings: MailMcpSettings | None = None,
        dialects: MailDialectRegistry | None = None,
    ) -> None:
        _logger.info("Initializing Mail tools provider")
        _logger.debug(
            "MailToolsProvider.__init__ arguments: mode=%s, owner_id=%s, "
            "mcp_settings_supplied=%s, dialects_supplied=%s, dataset_loader_type=%s",
            settings.mode.value,
            owner_id or settings.user_id,
            mcp_settings is not None,
            dialects is not None,
            type(dataset_loader).__name__,
        )
        self._settings = settings
        self._dataset_loader = dataset_loader
        self._owner_id = owner_id or settings.user_id
        self._mcp_settings = mcp_settings or MailMcpSettings()
        self._dialects = dialects or MailDialectRegistry()
        self._connection: McpConnection | None = None

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
            "MailToolsProvider._build_mcp arguments: base_path=%s, server=%s, owner_id=%s, timeout_seconds=%d",
            base_path,
            self._mcp_settings.server,
            self._owner_id,
            self._mcp_settings.request_timeout_seconds,
        )
        binding = self._binding(base_path)
        self._connection = McpConnection(
            binding,
            timeout_seconds=self._mcp_settings.request_timeout_seconds,
            auth=self._auth(binding),
        )
        tools = self._dialects.build(self._connection, binding, self._owner_id)
        _logger.debug(
            "Built MCP Mail tools backend: binding=%s, transport=%s, dialect=%s, tools_type=%s",
            binding.server,
            binding.transport.value,
            binding.dialect,
            type(tools).__name__,
        )
        return tools

    @staticmethod
    def _auth(binding: McpServerBinding) -> httpx.Auth | None:
        """Build the authentication a remote server requires.

        A stdio server runs as a local process and is trusted through the
        operating system, so it carries no credential of its own.
        """
        _logger.info("Selecting Mail MCP authentication")
        _logger.debug(
            "MailToolsProvider._auth arguments: server=%s, transport=%s, has_url=%s",
            binding.server,
            binding.transport.value,
            bool(binding.url),
        )
        if binding.transport is not McpTransport.HTTP:
            return None
        return MailOAuthProvider().build(binding.url)

    def _binding(self, base_path: Path | None) -> McpServerBinding:
        """Load the delivered description of the bound server."""
        _logger.info("Loading Mail MCP server binding")
        _logger.debug(
            "MailToolsProvider._binding arguments: base_path=%s, server=%s",
            base_path,
            self._mcp_settings.server,
        )
        directory = ConfigurationDirectory.resolve(base_path=base_path)
        return McpServerBindingLoader(directory).load(self._mcp_settings.server)
