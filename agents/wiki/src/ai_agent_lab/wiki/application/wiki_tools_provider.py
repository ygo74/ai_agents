"""Selection of the wiki MCP implementation for the configured runtime mode."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.config.settings import (
    WikiAgentMode,
    WikiAgentSettings,
    WikiMcpSettings,
)
from ai_agent_lab.wiki.inmemory.dataset import WikiDatasetLoader
from ai_agent_lab.wiki.inmemory.wiki_tools import InMemoryWikiTools
from ai_agent_lab.wiki.mcp.authorization import WikiAuthorization, authorization_for
from ai_agent_lab.wiki.mcp.binding import McpServerBinding, McpServerBindingLoader
from ai_agent_lab.wiki.mcp.connection import McpConnection
from ai_agent_lab.wiki.mcp.dialects import DialectContext, WikiDialectRegistry
from ai_agent_lab.wiki.tools_port import WikiTools

_logger = logging.getLogger(__name__)


class WikiToolsProvider:
    """Builds the wiki MCP implementation the configuration asks for.

    The agent and the skills are identical in every mode; only the object built
    here changes. That is the property the runtime modes exist to prove.

    In ``mcp`` mode the provider also reports what the bound server can serve, so
    a capability no server offers is never advertised to the model. That is not a
    theoretical nicety: `sooperset/mcp-atlassian` cannot list page revisions, and
    its binding says so.

    **A provider is built for one caller.** Over HTTP the connection carries that
    caller's ``Authorization`` header for the lifetime of the session, so sharing
    a provider between two people would serve the second one the first one's view
    of the wiki.
    """

    def __init__(
        self,
        settings: WikiAgentSettings,
        dataset_loader: WikiDatasetLoader,
        *,
        user_id: str = "",
        mcp_settings: WikiMcpSettings | None = None,
        dialects: WikiDialectRegistry | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._dataset_loader = dataset_loader
        self._user_id = user_id or settings.user_id
        self._mcp_settings = mcp_settings or WikiMcpSettings()
        self._dialects = dialects or WikiDialectRegistry()
        self._environment = dict(environment if environment is not None else os.environ)
        self._connection: McpConnection | None = None

    def build(self, *, base_path: Path | None = None) -> WikiTools:
        """Return the wiki tools matching the configured mode."""
        _logger.info("Building wiki tools for mode=%s", self._settings.mode.value)
        _logger.debug(
            "WikiToolsProvider settings: user_id=%s, server=%s, auth_scheme=%s",
            self._user_id,
            self._mcp_settings.server,
            self._mcp_settings.auth_scheme.value,
        )
        if self._settings.mode is WikiAgentMode.MOCK:
            return self._build_mock(base_path or Path.cwd())
        return self._build_mcp(base_path)

    def capabilities(self, *, base_path: Path | None = None) -> frozenset[WikiToolName]:
        """Return the capabilities the configured backend can actually serve.

        The deployment is taken into account, not just the file: a server started
        read-only exposes no write tool, so the write capabilities are withdrawn
        rather than offered to the model and refused on the first call.
        """
        if self._settings.mode is WikiAgentMode.MOCK:
            caps = frozenset(WikiToolName)
            _logger.debug("Mock mode capabilities count=%d", len(caps))
            return caps
        caps = self._binding(base_path).capabilities_in(self._environment)
        _logger.debug(
            "MCP binding '%s' capabilities count=%d: %s",
            self._mcp_settings.server,
            len(caps),
            [c.value for c in caps],
        )
        return caps

    async def aclose(self) -> None:
        """Close the MCP session, if one was opened."""
        if self._connection is None:
            return
        _logger.info("Closing MCP connection")
        await self._connection.aclose()
        self._connection = None

    def _build_mock(self, base_path: Path) -> WikiTools:
        """Build the wiki tools backed by the configured dataset."""
        dataset = self._settings.mock_dataset
        resolved = dataset if dataset.is_absolute() else base_path / dataset
        _logger.info("Building in-memory wiki tools from dataset: %s", resolved)
        return InMemoryWikiTools(self._dataset_loader.load_file(resolved))

    def _build_mcp(self, base_path: Path | None) -> WikiTools:
        """Build the client of the bound wiki MCP server.

        Over HTTP the caller's identity travels in a header, so it is resolved
        here, once, and the connection carries it. Over stdio there is no such
        header and the authorisation is empty, which is what tells the dialect it
        is speaking for exactly one person.
        """
        binding = self._binding(base_path)
        authorization = self._authorization()
        _logger.info(
            "Building MCP wiki tools with server='%s', dialect='%s', transport='%s'",
            binding.server,
            binding.dialect,
            binding.transport.value,
        )
        _logger.debug(
            "MCP connection config: timeout=%ss, is_per_user=%s, account_id=%s",
            self._mcp_settings.timeout_seconds,
            authorization.is_per_user,
            self._mcp_settings.account_id,
        )
        self._connection = McpConnection(
            binding,
            timeout_seconds=self._mcp_settings.timeout_seconds,
            headers=authorization.headers_for(self._caller()),
        )
        return self._dialects.build(
            self._connection,
            binding,
            DialectContext(
                account_id=self._mcp_settings.account_id,
                is_per_user=authorization.is_per_user,
            ),
        )

    def _authorization(self) -> WikiAuthorization:
        """Build the authorisation identifying the caller to a remote server."""
        _logger.debug(
            "Resolving authorization for scheme=%s, user=%s",
            self._mcp_settings.auth_scheme.value,
            self._user_id,
        )
        return authorization_for(
            self._mcp_settings.auth_scheme,
            user_id=self._user_id,
            account=self._mcp_settings.user_account,
            secret=self._mcp_settings.user_secret,
        )

    def _caller(self) -> UserContext:
        """The identity the connection is opened for.

        A minimal context: the authorisation only needs to know whose credential
        to look up, and building a full one here would suggest this is the
        context skills run under. It is not - that one comes from the composition
        root, carries permissions, and reaches every call.
        """
        return UserContext(user_id=self._user_id, session_id="mcp-connection")

    def _binding(self, base_path: Path | None) -> McpServerBinding:
        """Load the delivered description of the bound server."""
        directory = ConfigurationDirectory.resolve(base_path=base_path)
        return McpServerBindingLoader(directory).load(self._mcp_settings.server)
