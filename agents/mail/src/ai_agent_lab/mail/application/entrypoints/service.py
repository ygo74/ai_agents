"""Composition of the Mail Agent HTTP service.

Everything the application owns is assembled here: which caller a request is
attributed to, which conversation it continues, and what is done with a gated
operation. Everything the transport owns - routes, OpenAI payload shapes, JWT
validation, discovery - comes from ``ygo74-agent-runtime``.

Authentication is deliberately explicit. ``MAIL_AGENT_HTTP_API_KEY`` starts a
single-caller service for a demonstration; a Keycloak realm turns the same
service multi-user without touching a line of agent code. Both go through the
runtime's authenticator chain, so ``auth_context`` reaches the entrypoint the
same way and the agent cannot tell which was used.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from ygo74.agent_runtime.domains.auth.apikey_authenticator import StaticApiKeyUserResolver
from ygo74.agent_runtime.domains.auth.auth_context import ResolvedUser
from ygo74.agent_runtime.domains.auth.jwt_authenticator import JwksKeyResolver, JwtValidationConfig
from ygo74.agent_runtime.domains.discovery.agent_descriptor import AgentDescriptor
from ygo74.agent_runtime.domains.discovery.descriptor_registry import DescriptorRegistry
from ygo74.agent_runtime.domains.discovery.discovery_configuration import DiscoveryConfiguration
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity
from ygo74.agent_runtime.domains.endpoints.fastapi_endpoints import add_ai_endpoints
from ygo74.agent_runtime.domains.sessions.conversation_cache import ConversationRuntimeCache

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.core.config.environment import EnvironmentFile
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

    # Computed once and used twice: the authenticator chain is configured from
    # these, and the descriptor is derived from them. Discovery therefore cannot
    # advertise a scheme this service does not accept - including while the JWT
    # path below is switched off.
    jwt_validation = None
    api_key_resolver = _api_key_resolver(http, settings)

    add_ai_endpoints(
        app,
        MailAgentEntrypoint(MailConversationEngine(conversations)),
        default_route_key=AGENT_ID,
        enable_openai_chat_completions=True,
        enable_openai_responses=False,
        enable_anthropic_messages=False,
        jwt_validation=jwt_validation,
        # Always on, whichever credential the deployment uses. The runtime's
        # authenticator chain accepts the API key as well as a bearer token, so
        # this is not "tokens only": it is "something, always". Without it a
        # credential-less request is not refused at the door - it reaches the
        # entrypoint, finds no authenticated caller and dies as a 500, which
        # reads like a broken service rather than a working gate.
        require_bearer_token=True,
        api_key_resolver=api_key_resolver,
        descriptor_registry=DescriptorRegistry(
            [_descriptor(composition, jwt_validation=jwt_validation, api_key_resolver=api_key_resolver)]
        ),
        # Discovery carries its own authentication flag, defaulting to open.
        # Listing the agent also lists all fifteen capability descriptions, which
        # is a map of what the mailbox can be made to do: it is not public.
        discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
    )
    return app


def _refuse_an_open_service(http: MailAgentHttpSettings) -> None:
    """Fail loudly, and precisely, when nothing would identify a caller.

    The JWT path below is currently switched off in this build, so an issuer on
    its own authenticates nobody. Saying that here is the whole value of the
    guard: without it the service started, accepted every request, and served the
    configured mailbox to whoever asked - and the only symptom was a descriptor
    that could not be built.
    """
    if http.api_key:
        return
    if http.oidc_issuer:
        raise MailServiceConfigurationError(
            "MAIL_AGENT_HTTP_OIDC_ISSUER is set but the JWT path of this build is disabled, "
            "so no caller can be authenticated. Re-enable `jwt_validation` in build_app, "
            "or set MAIL_AGENT_HTTP_API_KEY for a single-caller demonstration"
        )
    raise MailServiceConfigurationError(
        "the Mail Agent HTTP service needs a caller: set MAIL_AGENT_HTTP_API_KEY "
        "for a single-caller demonstration, or configure and re-enable the JWT path"
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
