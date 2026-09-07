"""Selection of the mail MCP implementation for the configured runtime mode."""

from __future__ import annotations

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
        mcp_settings: MailMcpSettings | None = None,
        dialects: MailDialectRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._dataset_loader = dataset_loader
        self._mcp_settings = mcp_settings or MailMcpSettings()
        self._dialects = dialects or MailDialectRegistry()
        self._connection: McpConnection | None = None

    def build(self, *, base_path: Path | None = None) -> MailTools:
        """Return the mail tools matching the configured mode."""
        if self._settings.mode is MailAgentMode.MOCK:
            return self._build_mock(base_path or Path.cwd())
        return self._build_mcp(base_path)

    def capabilities(self, *, base_path: Path | None = None) -> frozenset[MailToolName]:
        """Return the capabilities the configured backend can actually serve."""
        if self._settings.mode is MailAgentMode.MOCK:
            return frozenset(MailToolName)
        return self._binding(base_path).capabilities

    async def aclose(self) -> None:
        """Close the MCP session, if one was opened."""
        if self._connection is None:
            return
        await self._connection.aclose()
        self._connection = None

    def _build_mock(self, base_path: Path) -> MailTools:
        """Build the mail tools backed by the configured dataset."""
        dataset = self._settings.mock_dataset
        resolved = dataset if dataset.is_absolute() else base_path / dataset
        return InMemoryMailTools(self._dataset_loader.load_file(resolved))

    def _build_mcp(self, base_path: Path | None) -> MailTools:
        """Build the client of the bound mail MCP server."""
        binding = self._binding(base_path)
        self._connection = McpConnection(
            binding,
            timeout_seconds=self._mcp_settings.request_timeout_seconds,
            auth=self._auth(binding),
        )
        return self._dialects.build(self._connection, binding, self._settings.user_id)

    @staticmethod
    def _auth(binding: McpServerBinding) -> httpx.Auth | None:
        """Build the authentication a remote server requires.

        A stdio server runs as a local process and is trusted through the
        operating system, so it carries no credential of its own.
        """
        if binding.transport is not McpTransport.HTTP:
            return None
        return MailOAuthProvider().build(binding.url)

    def _binding(self, base_path: Path | None) -> McpServerBinding:
        """Load the delivered description of the bound server."""
        directory = ConfigurationDirectory.resolve(base_path=base_path)
        return McpServerBindingLoader(directory).load(self._mcp_settings.server)
