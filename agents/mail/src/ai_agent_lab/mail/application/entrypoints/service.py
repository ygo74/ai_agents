"""Composition of the Mail Agent HTTP service.

Everything the application owns is assembled here: which caller a request is
attributed to, which conversation it continues, and what is done with a gated
operation. Everything the transport owns - routes, OpenAI payload shapes, JWT
validation, discovery - comes from ``ygo74-agent-runtime``.

Authentication is deliberately explicit. ``MAIL_AGENT_HTTP_API_KEY`` starts a
single-caller service for a demonstration; a Keycloak realm turns the same
service multi-user without touching a line of agent code. The runtime receives
one authentication policy, and ``auth_context`` reaches the entrypoint through
the same contract whichever identity provider is configured.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from ygo74.agent_runtime.domains.auth.apikey_authenticator import StaticApiKeyUserResolver
from ygo74.agent_runtime.domains.auth.auth_context import ResolvedUser
from ygo74.agent_runtime.domains.auth.authentication_policy import AuthenticationPolicy
from ygo74.agent_runtime.domains.auth.jwt_authenticator import JwksKeyResolver, JwtValidationConfig
from ygo74.agent_runtime.domains.configuration.environment import EnvironmentFile
from ygo74.agent_runtime.domains.discovery.agent_descriptor import AgentDescriptor
from ygo74.agent_runtime.domains.discovery.discovery_configuration import DiscoveryConfiguration
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity
from ygo74.agent_runtime.domains.endpoints.hosting_factory import EndpointSurface, HostingFactory
from ygo74.agent_runtime.domains.sessions.conversation_cache import ConversationRuntimeCache

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.maf.chat_client import MafChatClientFactory
from ai_agent_lab.mail.application.chat_client import ConfiguredChatClientFactory
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.application.entrypoints.conversation import (
    MailConversation,
    MailConversationEngine,
    MailConversationFactory,
)
from ai_agent_lab.mail.application.entrypoints.http import (
    MailAgentDescriptorFactory,
    MailAgentEntrypoint,
)
from ai_agent_lab.mail.config.http_settings import MailAgentHttpSettings
from ai_agent_lab.mail.config.settings import ChatClientSettings, MailAgentSettings

AGENT_ID = "mail-agent"

_logger = logging.getLogger(__name__)


class MailServiceConfigurationError(RuntimeError):
    """Raised when the service cannot be started safely as configured.

    Refusing to start is the point. A mail service with no way to identify its
    caller has no subject to partition state by and no mailbox to address, so it
    would serve one person's mail to whoever asked first.

    The Wiki Agent has carried this guard since it was written; the Mail Agent had
    not, and the gap was invisible because discovery used to assert two
    authentication schemes whether or not either was configured. Deriving the
    descriptor from the real configuration is what made it visible.
    """


def build_app(*, base_path: Path | None = None) -> FastAPI:
    """Assemble the HTTP service from the environment."""
    _logger.info("Building Mail Agent HTTP service")
    _logger.debug("build_app arguments: base_path=%s", base_path)
    EnvironmentFile().load()
    settings = MailAgentSettings()
    http = MailAgentHttpSettings.load()
    logging.basicConfig(level=settings.log_level.upper())

    _refuse_an_open_service(http)

    composition = MailAgentCompositionRoot(
        settings,
        ConfiguredChatClientFactory(
            ChatClientSettings(),
            MafChatClientFactory(),
            AzureIdentityCredentialProvider(),
        ).build(),
        base_path=base_path or Path.cwd(),
    )
    factory = MailConversationFactory(composition)
    conversations: ConversationRuntimeCache[MailConversation] = ConversationRuntimeCache(
        factory.build,
        MailConversationFactory.close,
        max_conversations=http.max_conversations,
        idle_lifetime=http.idle_lifetime(),
    )

    app = FastAPI(title="Mail Agent", lifespan=_closing(conversations))
    app.state.conversations = conversations

    # The same active credential configuration drives both request auth and the
    # descriptor, so discovery cannot advertise a scheme this service rejects.
    jwt_validation = _jwt_validation(http)
    api_key_resolver = _api_key_resolver(http, settings)
    if jwt_validation is not None:
        authentication = AuthenticationPolicy.jwt(jwt_validation)
    elif api_key_resolver is not None:
        authentication = AuthenticationPolicy.api_key(api_key_resolver)
    else:
        raise MailServiceConfigurationError("the Mail Agent HTTP service needs a caller")

    HostingFactory(app).add_agent(
        MailAgentEntrypoint(MailConversationEngine(conversations)),
        _descriptor(composition, jwt_validation=jwt_validation, api_key_resolver=api_key_resolver),
    ).add_ai_endpoints(
        EndpointSurface.OPENAI_CHAT_COMPLETIONS
    ).add_security(authentication).add_discovery(
        DiscoveryConfiguration(enable_openai_models=True, require_authentication=True)
    ).register()
    return app


def _refuse_an_open_service(http: MailAgentHttpSettings) -> None:
    """Fail loudly, and precisely, when nothing would identify a caller.

    A configured issuer enables the JWT path; without it, the static API key is
    the only supported caller identity.
    """
    if http.oidc_issuer or http.api_key:
        return
    raise MailServiceConfigurationError(
        "the Mail Agent HTTP service needs a caller: set MAIL_AGENT_HTTP_API_KEY "
        "for a single-caller demonstration, or set MAIL_AGENT_HTTP_OIDC_ISSUER for OIDC"
    )


def _closing(
    conversations: ConversationRuntimeCache[MailConversation],
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Release every open MCP session when the service stops.

    Conversations hold live connections, so a process that exits without
    closing them leaves sockets to be reaped by the operating system and,
    against a real server, sessions that look active long after they are not.
    """

    _logger.info("Configuring Mail Agent HTTP service shutdown")
    _logger.debug(
        "_closing arguments: conversations_type=%s",
        type(conversations).__name__,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _logger.info("Starting Mail Agent HTTP service lifespan")
        _logger.debug("lifespan arguments: app_title=%s", _app.title)
        try:
            yield
        finally:
            _logger.info("Closing Mail Agent HTTP conversations")
            await conversations.aclose()

    return lifespan


def _descriptor(
    composition: MailAgentCompositionRoot,
    *,
    jwt_validation: JwtValidationConfig | None,
    api_key_resolver: StaticApiKeyUserResolver | None,
) -> AgentDescriptor:
    """Describe the agent from the configuration it was built with.

    The authentication is read from the very values the endpoints are configured
    with, so a descriptor cannot claim a scheme this service refuses.
    """
    _logger.info("Building Mail Agent HTTP descriptor")
    _logger.debug("_descriptor arguments: composition_type=%s", type(composition).__name__)
    return MailAgentDescriptorFactory(
        composition.manifest(),
        security=AdvertisedSecurity.of(jwt_validation=jwt_validation, api_key_resolver=api_key_resolver),
        agent_id=AGENT_ID,
    ).build()


def _jwt_validation(http: MailAgentHttpSettings) -> JwtValidationConfig | None:
    """Build the token validation an OIDC deployment needs.

    Returning nothing when no issuer is configured is what keeps the API-key
    demonstration usable: the runtime then has no JWT authenticator to try.
    """
    _logger.info("Building Mail Agent JWT validation configuration")
    _logger.debug(
        "_jwt_validation arguments: issuer_configured=%s, audience=%s, "
        "roles_claim_path=%s, jwks_override_configured=%s",
        bool(http.oidc_issuer),
        http.oidc_audience,
        http.roles_claim_path,
        bool(http.jwks_url_override),
    )
    if not http.oidc_issuer:
        return None
    return JwtValidationConfig(
        allowed_algorithms=("RS256",),
        required_claims=("sub", "exp", "iss", "aud"),
        issuer=http.oidc_issuer,
        audience=http.oidc_audience,
        key_resolver=JwksKeyResolver(jwks_url=http.jwks_url()),
        roles_claim_path=http.roles_claim_path,
    )


def _api_key_resolver(
    http: MailAgentHttpSettings,
    settings: MailAgentSettings,
) -> StaticApiKeyUserResolver | None:
    """Map the demonstration key onto the configured local user.

    One key, one caller, stated in configuration. It exists so the LibreChat
    integration can be proved before a realm exists, and it is refused outright
    once an issuer is configured: two ways in is one too many.
    """
    _logger.info("Building Mail Agent API key resolver")
    _logger.debug(
        "_api_key_resolver arguments: api_key_configured=%s, issuer_configured=%s, "
        "user_id=%s, user_email_configured=%s",
        bool(http.api_key),
        bool(http.oidc_issuer),
        settings.user_id,
        bool(settings.user_email),
    )
    if not http.api_key:
        return None
    if http.oidc_issuer:
        _logger.warning("an OIDC issuer is configured; the static API key is ignored")
        return None
    return StaticApiKeyUserResolver(
        {
            http.api_key: ResolvedUser(
                user_id=settings.user_id,
                email=settings.user_email,
                name=settings.user_id,
            )
        }
    )
