"""Selection of the mail MCP implementation for the configured runtime mode."""

from __future__ import annotations

import logging
from pathlib import Path

from ygo74.agent_runtime.domains.auth.oauth_token_exchange import (
    Rfc8693OAuthOnBehalfOfTokenSource,
)
from ygo74.agent_runtime.domains.auth.tokens import OAuthOnBehalfOfTokenSource
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.mcp.binding import (
    McpConnection,
    McpServerBinding,
)
from ygo74.agent_runtime.domains.mcp.configuration import (
    McpAuthenticationMode,
    McpServerConfiguration,
)
from ygo74.agent_runtime.domains.mcp.dialects import DialectRegistry
from ygo74.agent_runtime.domains.mcp.registry import (
    McpAgentRegistry,
    McpAgentRegistryLoader,
    McpSkillServerView,
)

from ai_agent_lab.mail.application.ports.mail_tools import MailTools
from ai_agent_lab.mail.bootstrap.routed_mail_tools import RoutedMailTools
from ai_agent_lab.mail.bootstrap.scoped_mail_tools import ScopedMailTools
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
        manifest: AgentManifest | None = None,
        server: str | None = None,
        delegated_token_source: OAuthOnBehalfOfTokenSource | None = None,
        dialects: DialectRegistry[MailTools, [McpConnection, str]] | None = None,
    ) -> None:
        _logger.info("Initializing Mail tools provider")
        _logger.debug(
            "MailToolsProvider.__init__ arguments: mode=%s, owner_id=%s, "
            "server=%s, manifest_supplied=%s, delegated_token_source_supplied=%s, "
            "dialects_supplied=%s, dataset_loader_type=%s",
            settings.mode.value,
            owner_id or settings.user_id,
            server,
            manifest is not None,
            delegated_token_source is not None,
            dialects is not None,
            type(dataset_loader).__name__,
        )
        self._settings = settings
        self._dataset_loader = dataset_loader
        self._owner_id = owner_id or settings.user_id
        self._manifest = manifest
        self._server = server
        self._delegated_token_source = delegated_token_source
        self._dialects = dialects or create_dialect_registry()
        self._connection: McpConnection | None = None
        self._registry: McpAgentRegistry[MailToolName] | None = None
        self._configuration: McpServerConfiguration[MailToolName] | None = None
        self._resolved_binding: McpServerBinding[MailToolName] | None = None
        self._bindings: dict[str, McpServerBinding[MailToolName]] = {}
        self._tools_by_server: dict[str, MailTools] = {}
        self._mock_tools: MailTools | None = None
        self._closed = False

    @staticmethod
    def server_for(manifest: AgentManifest) -> str:
        """Select the legacy server: agent default, then the first skill override.

        This fallback is only for single-server access. Normal manifest execution
        resolves each skill independently through :meth:`build_for_skill`.
        """
        if manifest.mcp_server:
            return manifest.mcp_server
        for skill in manifest.skills:
            if skill.mcp_server:
                return skill.mcp_server
        raise McpBindingError("Mail MCP mode requires mcp_server in the agent manifest or skill manifests")

    def build(self, *, base_path: Path | None = None) -> MailTools:
        """Return the mail tools matching the configured mode.

        Manifest-driven access routes each operation to its corresponding skill.
        Reasoning skills use :meth:`build_for_skill` to keep their own server
        selection across all of their declared MCP calls.
        """
        _logger.info("Building Mail tools backend")
        _logger.debug(
            "MailToolsProvider.build arguments: mode=%s, base_path=%s, owner_id=%s",
            self._settings.mode.value,
            base_path,
            self._owner_id,
        )
        if self._settings.mode is MailAgentMode.MOCK:
            return self._mock_tools_for(base_path or Path.cwd())
        if self._manifest is None:
            return self._build_mcp_explicit(base_path)
        self._ensure_registry(ConfigurationDirectory.resolve(base_path=base_path))
        return RoutedMailTools(lambda name: self.build_for_skill(name, base_path=base_path))

    def build_for_skill(self, tool_name: str, *, base_path: Path | None = None) -> MailTools:
        """Return the mail tools backing one skill, scoped to its own MCP aliases.

        Sibling skills sharing one server share the same connection and the
        same underlying dialect object (constructed once per server), but
        each skill only ever receives a thin view restricted to its own
        manifest ``mcp_tools``: calling an operation its own skill does not
        declare fails explicitly instead of silently reaching the server
        through another skill's broader access.

        Args:
            tool_name: Manifest identity of the skill requesting tools.
            base_path: Delivered configuration root; defaults to the process root.
        """
        _logger.debug(
            "MailToolsProvider.build_for_skill arguments: tool_name=%s, base_path=%s", tool_name, base_path
        )
        if self._settings.mode is MailAgentMode.MOCK:
            return self._mock_tools_for(base_path or Path.cwd())
        if self._manifest is None:
            return self._build_mcp_explicit(base_path)
        directory = ConfigurationDirectory.resolve(base_path=base_path)
        registry = self._ensure_registry(directory)
        view = registry.for_skill(tool_name)
        shared = self._shared_tools_for_server(directory, view)
        return ScopedMailTools(tool_name, shared, view)

    def capabilities(self, *, base_path: Path | None = None) -> frozenset[MailToolName]:
        """Return the capabilities the configured backend can actually serve.

        For a manifest-driven multi-server registry this is the union of
        capabilities across every server referenced by the agent's skills;
        callers deciding whether one specific skill is servable should use
        :meth:`capabilities_for` with that skill's own tool name instead.

        This only reads delivered bindings, never opens a connection, so it
        never requires OAuth secrets that are only needed once a server is
        actually used.
        """
        _logger.info("Resolving Mail backend capabilities")
        _logger.debug(
            "MailToolsProvider.capabilities arguments: mode=%s, base_path=%s",
            self._settings.mode.value,
            base_path,
        )
        if self._settings.mode is MailAgentMode.MOCK:
            capabilities = frozenset(MailToolName)
        elif self._manifest is None:
            capabilities = self._binding_explicit(base_path).capabilities
        else:
            directory = ConfigurationDirectory.resolve(base_path=base_path)
            server_names = self._manifest_server_names()
            capabilities = (
                frozenset().union(*(self._binding_for_server(directory, name).capabilities for name in server_names))
                if server_names
                else frozenset()
            )
        _logger.debug(
            "Resolved Mail backend capabilities: count=%d, names=%s",
            len(capabilities),
            sorted(name.value for name in capabilities),
        )
        return capabilities

    def capabilities_for(self, tool_name: str, *, base_path: Path | None = None) -> frozenset[MailToolName]:
        """Return the capabilities of the specific server one skill resolves to.

        This only reads the delivered binding declared for that skill's
        effective server, never opening a connection.
        """
        if self._settings.mode is MailAgentMode.MOCK:
            return frozenset(MailToolName)
        if self._manifest is None:
            return self._binding_explicit(base_path).capabilities
        directory = ConfigurationDirectory.resolve(base_path=base_path)
        server_name = self._manifest_server_for(tool_name)
        declared = frozenset(MailToolName(alias) for alias in self._manifest.skill(tool_name).mcp_tools)
        return declared & self._binding_for_server(directory, server_name).capabilities

    async def aclose(self) -> None:
        """Close the MCP session, if one was opened."""
        _logger.info("Closing Mail tools provider")
        self._closed = True
        _logger.debug(
            "MailToolsProvider.aclose arguments: has_connection=%s",
            self._connection is not None,
        )
        if self._registry is not None:
            await self._registry.aclose()
            self._registry = None
        if self._connection is not None:
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

    def _mock_tools_for(self, base_path: Path) -> MailTools:
        """Return one shared in-memory backend so every skill sees the same mailbox state."""
        if self._mock_tools is None:
            self._mock_tools = self._build_mock(base_path)
        return self._mock_tools

    def _build_mcp_explicit(self, base_path: Path | None) -> MailTools:
        """Build the client of one explicitly named server without a manifest.

        One-off CLI authorisation uses an explicit server rather than an agent
        manifest; normal agent execution always uses the registry via
        :meth:`build_for_skill`.
        """
        if not self._server:
            raise McpBindingError("Mail MCP mode requires mcp_server in the agent manifest or skill manifests")
        if self._connection is not None and self._configuration is not None:
            return self._dialects.build(self._configuration.binding, self._connection, self._owner_id)
        self._configuration = load_configuration(ConfigurationDirectory.resolve(base_path=base_path), self._server)
        self._connection = MailMcpConnectionFactory().build(
            self._configuration,
            delegated_token_source=self._source_for_configuration(self._configuration),
        )
        tools = self._dialects.build(self._configuration.binding, self._connection, self._owner_id)
        _logger.debug(
            "Built MCP Mail tools backend: binding=%s, transport=%s, dialect=%s, tools_type=%s",
            self._configuration.binding.server,
            self._configuration.binding.transport.value,
            self._configuration.binding.dialect,
            type(tools).__name__,
        )
        return tools

    def _source_for_configuration(
        self,
        configuration: McpServerConfiguration[MailToolName],
    ) -> OAuthOnBehalfOfTokenSource | None:
        """Use the injected source or build RFC 8693 from the selected server settings.

        Args:
            configuration: Validated settings for the selected MCP server.

        Raises:
            McpBindingError: OBO is selected but its client settings are absent.
        """
        if self._delegated_token_source is not None:
            return self._delegated_token_source
        if configuration.authentication_mode is not McpAuthenticationMode.OAUTH_ON_BEHALF_OF:
            return None
        settings = configuration.delegated_oauth
        if (
            settings is None
            or settings.token_url is None
            or settings.client_id is None
            or settings.client_secret is None
        ):
            raise McpBindingError("Mail MCP OBO requires token_url, client_id, and client_secret in the server YAML")
        return Rfc8693OAuthOnBehalfOfTokenSource(settings)

    def _binding_explicit(self, base_path: Path | None) -> McpServerBinding[MailToolName]:
        """Load the delivered description of the explicitly named server (no manifest)."""
        _logger.info("Loading Mail MCP server binding")
        _logger.debug(
            "MailToolsProvider._binding_explicit arguments: base_path=%s, server=%s",
            base_path,
            self._server,
        )
        if self._configuration is not None:
            return self._configuration.binding
        if self._resolved_binding is not None:
            return self._resolved_binding
        if not self._server:
            raise McpBindingError("Mail MCP mode requires mcp_server in the agent manifest or skill manifests")
        directory = ConfigurationDirectory.resolve(base_path=base_path)
        self._resolved_binding = load_binding(directory, self._server)
        return self._resolved_binding

    def _ensure_registry(self, directory: ConfigurationDirectory) -> McpAgentRegistry[MailToolName]:
        """Load the per-skill registry once and reuse it for every subsequent call."""
        if self._closed:
            raise McpBindingError("Mail MCP registry is closed")
        if self._manifest is None:
            raise McpBindingError("Mail MCP registry routing requires an agent manifest")
        if self._registry is None:
            self._registry = McpAgentRegistryLoader(
                directory,
                MailToolName,
                delegated_token_source=self._delegated_token_source,
                error_factory=McpBindingError,
            ).load(self._serviceable_manifest(directory))
        return self._registry

    def _serviceable_manifest(self, directory: ConfigurationDirectory) -> AgentManifest:
        """Keep unsupported capabilities out of the runtime's strict alias validation."""
        if self._manifest is None:
            raise McpBindingError("Mail MCP registry routing requires an agent manifest")
        skills = []
        for skill in self._manifest.skills:
            if not skill.mcp_tools:
                skills.append(skill)
                continue
            binding = self._binding_for_server(directory, self._manifest_server_for(skill.tool_name))
            if frozenset(MailToolName(alias) for alias in skill.mcp_tools) <= binding.capabilities:
                skills.append(skill)
        return self._manifest.model_copy(update={"skills": tuple(skills)})

    def _shared_tools_for_server(
        self,
        directory: ConfigurationDirectory,
        view: McpSkillServerView,
    ) -> MailTools:
        """Return the one dialect object built once per server, shared across its skills."""
        server_name = view.server_name
        shared = self._tools_by_server.get(server_name)
        if shared is None:
            binding = self._binding_for_server(directory, server_name)
            shared = self._dialects.build(binding, view.connection, self._owner_id)
            self._tools_by_server[server_name] = shared
        return shared

    def _binding_for_server(
        self, directory: ConfigurationDirectory, server_name: str
    ) -> McpServerBinding[MailToolName]:
        """Load and cache the delivered binding for one distinct server name."""
        binding = self._bindings.get(server_name)
        if binding is None:
            binding = load_binding(directory, server_name)
            self._bindings[server_name] = binding
        return binding

    def _manifest_server_for(self, tool_name: str) -> str:
        """Return the effective server name declared for one skill, without opening it."""
        if self._manifest is None:
            raise McpBindingError("Mail MCP registry routing requires an agent manifest")
        skill = self._manifest.skill(tool_name)
        server_name = skill.mcp_server or self._manifest.mcp_server
        if not server_name:
            raise McpBindingError(f"skill {tool_name!r} declares no effective MCP server")
        return server_name

    def _manifest_server_names(self) -> tuple[str, ...]:
        """Return every distinct server name referenced by MCP-enabled skills."""
        if self._manifest is None:
            return ()
        names: list[str] = []
        for skill in self._manifest.skills:
            if not skill.mcp_tools:
                continue
            server_name = skill.mcp_server or self._manifest.mcp_server
            if server_name and server_name not in names:
                names.append(server_name)
        return tuple(names)
