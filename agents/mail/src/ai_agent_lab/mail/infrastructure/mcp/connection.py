"""Construct Mail connections from the runtime's validated server configuration."""

from ygo74.agent_runtime.domains.mcp.binding import McpConnection
from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode, McpServerConfiguration
from ygo74.agent_runtime.domains.mcp.oauth import McpOAuthProviderFactory

from ai_agent_lab.mail.application.errors import MailToolUnavailableError
from ai_agent_lab.mail.domain.operation_names import MailToolName
from ai_agent_lab.mail.infrastructure.mcp.errors import McpBindingError


class MailMcpConnectionFactory:
    """Apply the selected server's authentication, timeout, headers, and network options."""

    def build(self, configuration: McpServerConfiguration[MailToolName]) -> McpConnection:
        auth = None
        if configuration.authentication_mode is McpAuthenticationMode.OAUTH:
            if configuration.oauth is None:
                raise McpBindingError(f"server {configuration.binding.server!r} is missing OAuth settings")
            auth = McpOAuthProviderFactory().build(configuration.binding.url, configuration.oauth)
        if (
            configuration.authentication_mode is McpAuthenticationMode.OAUTH_ON_BEHALF_OF
            and configuration.delegated_oauth is None
        ):
            raise McpBindingError(f"server {configuration.binding.server!r} is missing delegated OAuth settings")
        return McpConnection(
            configuration.binding,
            timeout_seconds=configuration.request_timeout_seconds,
            auth=auth,
            headers=configuration.headers,
            network=configuration.network,
            delegated_oauth=configuration.delegated_oauth,
            unavailable=MailToolUnavailableError,
        )
