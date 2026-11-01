"""Apply Wiki connection policy while retaining the runtime registry's ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.mcp.binding import McpConnection
from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode, McpServerConfiguration
from ygo74.agent_runtime.domains.mcp.registry import McpAgentRegistryLoader
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.domain.operation_names import WikiToolName
from ai_agent_lab.wiki.infrastructure.configuration.settings import WikiMcpSettings
from ai_agent_lab.wiki.infrastructure.mcp.authorization import WikiAuthorization
from ai_agent_lab.wiki.infrastructure.mcp.configuration import with_resolved_stdio_environment
from ai_agent_lab.wiki.infrastructure.mcp.errors import McpBindingError


class WikiMcpRegistryLoader(McpAgentRegistryLoader[WikiToolName]):
    """Preserve legacy caller headers and stdio variables on each owned connection."""

    def __init__(
        self,
        directory: ConfigurationDirectory,
        *,
        settings: WikiMcpSettings,
        user: UserContext,
        environment: Mapping[str, str],
        authorization: Callable[[], WikiAuthorization],
    ) -> None:
        super().__init__(directory, WikiToolName, environment=environment, error_factory=McpBindingError)
        self._settings = settings
        self._user = user
        self._wiki_environment = environment
        self._authorization = authorization

    def _create_connection(self, configuration: McpServerConfiguration[WikiToolName]) -> McpConnection:
        binding = with_resolved_stdio_environment(configuration.binding, self._wiki_environment)
        configuration = replace(configuration, binding=binding)
        if configuration.authentication_mode is not McpAuthenticationMode.NONE:
            return super()._create_connection(configuration)
        # Resolve only legacy authentication; explicit YAML auth belongs to the runtime.
        authorization = self._authorization()
        configuration = replace(
            configuration,
            headers={**configuration.headers, **authorization.headers_for(self._user)},
            request_timeout_seconds=self._settings.timeout_seconds,
        )
        return super()._create_connection(configuration)
