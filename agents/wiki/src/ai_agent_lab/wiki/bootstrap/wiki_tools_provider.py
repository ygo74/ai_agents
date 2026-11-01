"""Selection of the wiki MCP implementation for the configured runtime mode."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.mcp.binding import McpConnection, McpServerBinding
from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode, McpServerConfiguration
from ygo74.agent_runtime.domains.mcp.dialects import DialectRegistry
from ygo74.agent_runtime.domains.mcp.registry import McpAgentRegistry, McpSkillServerView
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.application.ports.wiki_tools import WikiTools
from ai_agent_lab.wiki.bootstrap.routed_wiki_tools import RoutedWikiTools
from ai_agent_lab.wiki.bootstrap.scoped_wiki_tools import ScopedWikiTools
from ai_agent_lab.wiki.domain.auth import WikiAuthScheme
from ai_agent_lab.wiki.domain.operation_names import WikiToolName
from ai_agent_lab.wiki.domain.tool_errors import WikiToolUnavailableError
from ai_agent_lab.wiki.infrastructure.configuration.settings import (
    WikiAgentMode,
    WikiAgentSettings,
    WikiMcpSettings,
)
from ai_agent_lab.wiki.infrastructure.inmemory.dataset import WikiDatasetLoader
from ai_agent_lab.wiki.infrastructure.inmemory.wiki_tools import InMemoryWikiTools
from ai_agent_lab.wiki.infrastructure.mcp.authorization import WikiAuthorization, WikiUserCredentials, authorization_for
from ai_agent_lab.wiki.infrastructure.mcp.configuration import (
    capabilities_in,
    load_binding,
    load_configuration,
    with_resolved_stdio_environment,
)
from ai_agent_lab.wiki.infrastructure.mcp.dialects import DialectContext, create_dialect_registry
from ai_agent_lab.wiki.infrastructure.mcp.errors import McpBindingError
from ai_agent_lab.wiki.infrastructure.mcp.registry import WikiMcpRegistryLoader

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
        manifest: AgentManifest | None = None,
        server: str | None = None,
        mcp_settings: WikiMcpSettings | None = None,
        dialects: DialectRegistry[WikiTools, [McpConnection, DialectContext]] | None = None,
        environment: Mapping[str, str] | None = None,
        credentials: WikiUserCredentials | None = None,
    ) -> None:
        self._settings = settings
        self._dataset_loader = dataset_loader
        self._user_id = user_id or settings.user_id
        self._mcp_settings = mcp_settings or WikiMcpSettings()
        self._credentials = credentials
        self._manifest = manifest
        self._explicit_server = server
        self._dialects = dialects or create_dialect_registry()
        self._environment = dict(environment if environment is not None else os.environ)
        self._connection: McpConnection | None = None
        self._registry: McpAgentRegistry[WikiToolName] | None = None
        self._bindings: dict[str, McpServerBinding[WikiToolName]] = {}
        self._configurations: dict[str, McpServerConfiguration[WikiToolName]] = {}
        self._tools_by_server: dict[str, WikiTools] = {}
        self._mock_tools: WikiTools | None = None
        self._closed = False

    @property
    def _server(self) -> str:
        """The legacy single server: explicit override, else manifest default, else settings."""
        if self._explicit_server:
            return self._explicit_server
        if self._manifest is not None:
            return self.server_for(self._manifest)
        return self._mcp_settings.server

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
        raise McpBindingError("Wiki MCP mode requires mcp_server in the agent manifest or skill manifests")

    def build(self, *, base_path: Path | None = None) -> WikiTools:
        """Return the wiki tools matching the configured mode.

        Manifest-driven access routes each standalone operation through its own
        skill. Reasoning skills use :meth:`build_for_skill` to keep their own
        server and alias scope across all their reads.
        """
        _logger.info("Building wiki tools for mode=%s", self._settings.mode.value)
        _logger.debug(
            "WikiToolsProvider settings: user_id=%s, auth_scheme=%s",
            self._user_id,
            self._mcp_settings.auth_scheme.value,
        )
        if self._settings.mode is WikiAgentMode.MOCK:
            return self._mock_tools_for(base_path or Path.cwd())
        if self._manifest is None:
            return self._build_mcp_explicit(base_path)
        self._ensure_registry(self._directory(base_path))
        return RoutedWikiTools(lambda name: self.build_for_skill(name, base_path=base_path))

    def build_for_skill(self, tool_name: str, *, base_path: Path | None = None) -> WikiTools:
        """Return the wiki tools backing one skill, scoped to its own MCP aliases.

        Sibling skills sharing one server share the same connection and the
        same underlying dialect object (constructed once per server), but each
        skill only ever receives a thin view restricted to its own manifest
        ``mcp_tools``: calling an operation its own skill does not declare
        fails explicitly instead of silently reaching the server through
        another skill's broader access.

        With a manifest, missing or unexposed skills raise instead of borrowing
        another skill's server. Without a manifest, the legacy settings-driven
        client is returned without per-skill routing.

        Args:
            tool_name: Manifest identity of the skill requesting tools.
            base_path: Delivered configuration root; defaults to the process root.
        """
        _logger.debug("WikiToolsProvider.build_for_skill arguments: tool_name=%s, base_path=%s", tool_name, base_path)
        if self._settings.mode is WikiAgentMode.MOCK:
            return self._mock_tools_for(base_path or Path.cwd())
        if self._manifest is None:
            return self._build_mcp_explicit(base_path)
        directory = self._directory(base_path)
        registry = self._ensure_registry(directory)
        view = registry.for_skill(tool_name)
        shared = self._shared_tools_for_server(directory, view)
        return ScopedWikiTools(tool_name, shared, view)

    def capabilities(self, *, base_path: Path | None = None) -> frozenset[WikiToolName]:
        """Return the capabilities the configured backend can actually serve.

        For a manifest-driven multi-server registry this is the union of
        capabilities across every server referenced by an MCP-enabled skill;
        callers deciding whether one specific skill is servable should use
        :meth:`capabilities_for` with that skill's own tool name instead.

        The deployment is taken into account, not just the file: a server
        started read-only exposes no write tool, so the write capabilities are
        withdrawn rather than offered to the model and refused on the first
        call. This only reads delivered bindings, never opens a connection.
        """
        if self._settings.mode is WikiAgentMode.MOCK:
            caps = frozenset(WikiToolName)
            _logger.debug("Mock mode capabilities count=%d", len(caps))
            return caps
        if self._manifest is None:
            caps = capabilities_in(self._binding_explicit(base_path), self._environment)
        else:
            directory = self._directory(base_path)
            server_names = self._manifest_server_names()
            caps = (
                frozenset().union(
                    *(
                        capabilities_in(self._binding_for_server(directory, name), self._environment)
                        for name in server_names
                    )
                )
                if server_names
                else frozenset()
            )
        _logger.debug(
            "Resolved wiki backend capabilities: count=%d, names=%s",
            len(caps),
            sorted(c.value for c in caps),
        )
        return caps

    def capabilities_for(self, tool_name: str, *, base_path: Path | None = None) -> frozenset[WikiToolName]:
        """Return the capabilities of the specific server one skill resolves to.

        This only reads the delivered binding declared for that skill's
        effective server, never opening a connection.
        """
        if self._settings.mode is WikiAgentMode.MOCK:
            return frozenset(WikiToolName)
        if self._manifest is None:
            return capabilities_in(self._binding_explicit(base_path), self._environment)
        directory = self._directory(base_path)
        server_name = self._manifest_server_for(tool_name)
        declared = frozenset(WikiToolName(alias) for alias in self._manifest.skill(tool_name).mcp_tools)
        return declared & capabilities_in(self._binding_for_server(directory, server_name), self._environment)

    async def aclose(self) -> None:
        """Close the MCP session(s), if any were opened."""
        self._closed = True
        if self._registry is not None:
            _logger.info("Closing wiki MCP registry")
            await self._registry.aclose()
            self._registry = None
        if self._connection is not None:
            _logger.info("Closing MCP connection")
            await self._connection.aclose()
            self._connection = None

    def _build_mock(self, base_path: Path) -> WikiTools:
        """Build the wiki tools backed by the configured dataset."""
        dataset = self._settings.mock_dataset
        resolved = dataset if dataset.is_absolute() else base_path / dataset
        _logger.info("Building in-memory wiki tools from dataset: %s", resolved)
        return InMemoryWikiTools(self._dataset_loader.load_file(resolved))

    def _mock_tools_for(self, base_path: Path) -> WikiTools:
        """Return one shared in-memory backend so every skill sees the same wiki state."""
        if self._mock_tools is None:
            self._mock_tools = self._build_mock(base_path)
        return self._mock_tools

    def _build_mcp_explicit(self, base_path: Path | None) -> WikiTools:
        """Build the client of one explicitly named server without per-skill routing.

        Only deployments without a manifest use this path. Manifest execution
        uses the registry, even when no MCP-enabled skill is available.

        Legacy headers are resolved once per connection. Fixed settings credentials
        belong to the configured owner; only an injected credential source can
        provide different credentials for different callers.
        """
        server = self._server
        if self._connection is not None:
            cached = self._bindings.get(server)
            if cached is not None:
                return self._dialects.build(cached, self._connection, self._explicit_context())
        binding = with_resolved_stdio_environment(load_binding(self._directory(base_path), server), self._environment)
        self._bindings[server] = binding
        authorization = self._authorization()
        _logger.info(
            "Building MCP wiki tools with server='%s', dialect='%s', transport='%s'",
            binding.server,
            binding.dialect,
            binding.transport.value,
        )
        context = self._explicit_context()
        _logger.debug(
            "MCP connection config: timeout=%ss, is_per_user=%s, account_id=%s",
            self._mcp_settings.timeout_seconds,
            context.is_per_user,
            context.account_id,
        )
        self._connection = McpConnection(
            binding,
            timeout_seconds=self._mcp_settings.timeout_seconds,
            headers=authorization.headers_for(self._caller()),
            unavailable=WikiToolUnavailableError,
        )
        return self._dialects.build(binding, self._connection, context)

    def _explicit_context(self) -> DialectContext:
        """Keep the owner guard unless credentials come from a caller-bound source."""
        authorization = self._authorization()
        fixed_credential = self._credentials is None and authorization.scheme is not WikiAuthScheme.NONE
        return DialectContext(
            account_id=self._settings.user_id if fixed_credential else self._mcp_settings.account_id,
            is_per_user=self._credentials is not None and authorization.is_per_user,
        )

    def _authorization(self) -> WikiAuthorization:
        """Build the authorisation identifying the caller to a remote server."""
        _logger.debug(
            "Resolving authorization for scheme=%s, user=%s",
            self._mcp_settings.auth_scheme.value,
            self._user_id,
        )
        if self._credentials is not None:
            return WikiAuthorization(self._mcp_settings.auth_scheme, self._credentials)
        # Deployment credentials belong to the configured owner, never the current request subject.
        return authorization_for(
            self._mcp_settings.auth_scheme,
            user_id=self._settings.user_id,
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

    def _binding_explicit(self, base_path: Path | None) -> McpServerBinding[WikiToolName]:
        """Load the delivered description of the explicitly named server (legacy path)."""
        server = self._server
        cached = self._bindings.get(server)
        if cached is not None:
            return cached
        binding = load_binding(self._directory(base_path), server)
        self._bindings[server] = binding
        return binding

    def _ensure_registry(self, directory: ConfigurationDirectory) -> McpAgentRegistry[WikiToolName]:
        """Load the per-skill registry once and reuse it for every subsequent call."""
        if self._closed:
            raise McpBindingError("Wiki MCP registry is closed")
        if self._manifest is None:
            raise McpBindingError("Wiki MCP registry routing requires an agent manifest")
        if self._registry is None:
            self._registry = WikiMcpRegistryLoader(
                directory,
                settings=self._mcp_settings,
                user=self._caller(),
                environment=self._environment,
                authorization=self._authorization,
            ).load(self._serviceable_manifest(directory))
        return self._registry

    def _serviceable_manifest(self, directory: ConfigurationDirectory) -> AgentManifest:
        """Keep unsupported capabilities out of the runtime's strict alias validation."""
        if self._manifest is None:
            raise McpBindingError("Wiki MCP registry routing requires an agent manifest")
        skills = []
        for skill in self._manifest.skills:
            if not skill.mcp_tools:
                skills.append(skill)
                continue
            binding = self._binding_for_server(directory, self._manifest_server_for(skill.tool_name))
            required = frozenset(WikiToolName(alias) for alias in skill.mcp_tools)
            if required <= capabilities_in(binding, self._environment):
                skills.append(skill)
        return self._manifest.model_copy(update={"skills": tuple(skills)})

    def _shared_tools_for_server(
        self,
        directory: ConfigurationDirectory,
        view: McpSkillServerView,
    ) -> WikiTools:
        """Return the one dialect object built once per server, shared across its skills.

        Explicit YAML authentication is owned by the runtime connection. For
        ``NONE`` authentication, the Wiki registry loader adds legacy headers to
        the connection. The dialect receives only the owner/caller-bound guard
        context, never credentials.
        """
        server_name = view.server_name
        shared = self._tools_by_server.get(server_name)
        if shared is None:
            binding = self._binding_for_server(directory, server_name)
            configuration = self._configuration_for(directory, server_name)
            context = (
                self._explicit_context()
                if configuration.authentication_mode is McpAuthenticationMode.NONE
                else DialectContext(account_id=self._mcp_settings.account_id, is_per_user=False)
            )
            shared = self._dialects.build(binding, view.connection, context)
            self._tools_by_server[server_name] = shared
        return shared

    def _configuration_for(
        self, directory: ConfigurationDirectory, server_name: str
    ) -> McpServerConfiguration[WikiToolName]:
        """Load and cache one server's full configuration, including its auth mode."""
        cached = self._configurations.get(server_name)
        if cached is not None:
            return cached
        configuration = load_configuration(directory, server_name, environment=self._environment)
        self._configurations[server_name] = configuration
        return configuration

    def _binding_for_server(
        self, directory: ConfigurationDirectory, server_name: str
    ) -> McpServerBinding[WikiToolName]:
        """Load and cache the delivered binding for one distinct server name."""
        binding = self._bindings.get(server_name)
        if binding is None:
            binding = with_resolved_stdio_environment(load_binding(directory, server_name), self._environment)
            self._bindings[server_name] = binding
        return binding

    def _manifest_server_for(self, tool_name: str) -> str:
        """Return the effective server name declared for one skill, without opening it."""
        if self._manifest is None:
            raise McpBindingError("Wiki MCP registry routing requires an agent manifest")
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

    def _directory(self, base_path: Path | None) -> ConfigurationDirectory:
        """Resolve the delivered configuration root once per call."""
        return ConfigurationDirectory.resolve(base_path=base_path)
