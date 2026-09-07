"""Selection of the mail MCP implementation for the configured runtime mode."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from ai_agent_lab.infrastructure.config.directory import ConfigurationDirectory
from ai_agent_lab.infrastructure.config.mcp_binding import McpServerBinding, McpServerBindingLoader
from ai_agent_lab.infrastructure.config.settings import (
    MailAgentMode,
    MailAgentSettings,
    MailMcpSettings,
    McpTransport,
)
from ai_agent_lab.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.infrastructure.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.infrastructure.mcp.connection import McpConnection
from ai_agent_lab.infrastructure.mcp.gmail.mail_tools import GmailMailTools
from ai_agent_lab.infrastructure.mcp.mail_tools import McpMailTools
from ai_agent_lab.infrastructure.mcp.oauth import MailOAuthProvider
from ai_agent_lab.mcp.mail.catalog import MailToolName
from ai_agent_lab.mcp.mail.contracts import MailTools
from ai_agent_lab.mcp.mail.errors import MailToolUnavailableError

DialectFactory = Callable[[McpConnection, McpServerBinding, str], MailTools]


def _native(connection: McpConnection, binding: McpServerBinding, owner_id: str) -> MailTools:
    """Build the client of a server implementing our contract."""
    return McpMailTools(connection, binding, owner_id=owner_id)


def _gmail(connection: McpConnection, binding: McpServerBinding, owner_id: str) -> MailTools:
    """Build the client of the official Gmail server."""
    return GmailMailTools(connection, binding, owner_id=owner_id)


_DIALECTS: dict[str, DialectFactory] = {"native": _native, "gmail": _gmail}


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
    ) -> None:
        self._settings = settings
        self._dataset_loader = dataset_loader
        self._mcp_settings = mcp_settings or MailMcpSettings()
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
        build = _DIALECTS.get(binding.dialect)
        if build is None:
            raise MailToolUnavailableError(
                f"server {binding.server!r} speaks the {binding.dialect!r} dialect, which is not implemented. "
                f"Known dialects: {', '.join(sorted(_DIALECTS))}."
            )
        self._connection = McpConnection(
            binding,
            timeout_seconds=self._mcp_settings.request_timeout_seconds,
            auth=self._auth(binding),
        )
        return build(self._connection, binding, self._settings.user_id)

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
