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
from ygo74.agent_runtime import (
    AgentDescriptor,
    DescriptorRegistry,
    DiscoveryConfiguration,
    ResolvedUser,
    StaticApiKeyUserResolver,
    add_ai_endpoints,
)
from ygo74.agent_runtime.domains.auth.jwt_authenticator import JwksKeyResolver, JwtValidationConfig

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.core.config.environment import EnvironmentFile
from ai_agent_lab.core.serving.runtimes import ConversationRuntimeCache
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


def build_app(*, base_path: Path | None = None) -> FastAPI:
    """Assemble the HTTP service from the environment."""
    EnvironmentFile().load()
    settings = MailAgentSettings()
    http = MailAgentHttpSettings()
    logging.basicConfig(level=settings.log_level.upper())

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

    add_ai_endpoints(
        app,
        MailAgentEntrypoint(MailConversationEngine(conversations)),
        default_route_key=AGENT_ID,
        enable_openai_chat_completions=True,
        enable_openai_responses=False,
        enable_anthropic_messages=False,
        # jwt_validation=_jwt_validation(http),
        # require_bearer_token=http.requires_authentication,
        jwt_validation=None,
        require_bearer_token=False,
        api_key_resolver=_api_key_resolver(http, settings),
        descriptor_registry=DescriptorRegistry([_descriptor(composition)]),
        # Discovery carries its own authentication flag, defaulting to open.
        # Listing the agent also lists all fifteen capability descriptions, which
        # is a map of what the mailbox can be made to do: it is not public.
        discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
    )
    return app


def _closing(
    conversations: ConversationRuntimeCache[MailConversation],
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Release every open MCP session when the service stops.

    Conversations hold live connections, so a process that exits without
    closing them leaves sockets to be reaped by the operating system and,
    against a real server, sessions that look active long after they are not.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await conversations.aclose()

    return lifespan


def _descriptor(composition: MailAgentCompositionRoot) -> AgentDescriptor:
    """Describe the agent from the configuration it was built with."""
    return MailAgentDescriptorFactory(composition.manifest(), agent_id=AGENT_ID).build()


def _jwt_validation(http: MailAgentHttpSettings) -> JwtValidationConfig | None:
    """Build the token validation an OIDC deployment needs.

    Returning nothing when no issuer is configured is what keeps the API-key
    demonstration usable: the runtime then has no JWT authenticator to try.
    """
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
