"""Composition of the Wiki Agent HTTP service.

Everything the application owns is assembled here: which caller a request is
attributed to, which conversation it continues, and what is done with a gated
operation. Everything the transport owns - routes, OpenAI payload shapes, JWT
validation, discovery - comes from ``ygo74-agent-runtime``.

Authentication is deliberately explicit, and deliberately layered.
``WIKI_AGENT_HTTP_OIDC_ISSUER`` turns the service multi-user: every request
carries a token the runtime validates against the realm's published keys, and the
subject of that token is the person the agent acts for. Without an issuer,
``WIKI_AGENT_HTTP_API_KEY`` starts a single-caller service for a demonstration.
Both go through the runtime's authenticator chain, so ``auth_context`` reaches
the entrypoint the same way and the agent cannot tell which was used.

The two are mutually exclusive on purpose: two ways in is one too many, and a
static key left behind next to a configured realm is exactly the kind of
leftover that outlives the demonstration it was added for.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from langchain_core.language_models import BaseChatModel
from ygo74.agent_runtime import (
    AgentDescriptor,
    DescriptorRegistry,
    DiscoveryConfiguration,
    ResolvedUser,
    StaticApiKeyUserResolver,
    add_ai_endpoints,
)
from ygo74.agent_runtime.domains.auth.jwt_authenticator import JwksKeyResolver, JwtValidationConfig
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity
from ygo74.agent_runtime.domains.sessions.conversation_cache import ConversationRuntimeCache

from ai_agent_lab.core.config.environment import EnvironmentFile
from ai_agent_lab.wiki.application.cli_entrypoint import build_chat_model
from ai_agent_lab.wiki.application.composition import WikiAgentCompositionRoot
from ai_agent_lab.wiki.application.entrypoints.conversation import (
    WikiConversation,
    WikiConversationEngine,
    WikiConversationFactory,
)
from ai_agent_lab.wiki.application.entrypoints.http import (
    WikiAgentDescriptorFactory,
    WikiAgentEntrypoint,
)
from ai_agent_lab.wiki.config.http_settings import WikiAgentHttpSettings
from ai_agent_lab.wiki.config.settings import WikiAgentSettings

AGENT_ID = "wiki-agent"

_logger = logging.getLogger(__name__)


class WikiServiceConfigurationError(RuntimeError):
    """Raised when the service cannot be started safely as configured.

    Refusing to start is the point. A wiki service with no way to identify its
    caller has no subject to partition state by and no identity to present to
    Confluence, so it would serve one person's restricted spaces to whoever
    asked first.
    """


def build_app(
    *,
    base_path: Path | None = None,
    chat_model: BaseChatModel | None = None,
) -> FastAPI:
    """Assemble the HTTP service from the environment."""
    EnvironmentFile().load()
    settings = WikiAgentSettings()
    http = WikiAgentHttpSettings.load()
    logging.basicConfig(level=settings.log_level.upper())

    _refuse_an_open_service(http)

    composition = WikiAgentCompositionRoot(
        settings,
        chat_model or build_chat_model(),
        base_path=base_path or Path.cwd(),
    )
    factory = WikiConversationFactory(composition)
    conversations: ConversationRuntimeCache[WikiConversation] = ConversationRuntimeCache(
        factory.build,
        WikiConversationFactory.close,
        max_conversations=http.max_conversations,
        idle_lifetime=http.idle_lifetime(),
    )

    app = FastAPI(title="Wiki Agent", lifespan=_closing(conversations))
    app.state.conversations = conversations

    # Computed once and used twice: the authenticator chain is configured from
    # these, and the descriptor is derived from them, so discovery cannot
    # advertise a scheme this service does not accept.
    jwt_validation = _jwt_validation(http)
    api_key_resolver = _api_key_resolver(http, settings)

    add_ai_endpoints(
        app,
        WikiAgentEntrypoint(WikiConversationEngine(conversations)),
        default_route_key=AGENT_ID,
        enable_openai_chat_completions=True,
        enable_openai_responses=False,
        enable_anthropic_messages=False,
        jwt_validation=jwt_validation,
        # Always on, whichever credential the deployment uses. The runtime's
        # authenticator chain accepts the API key as well as a bearer token, so
        # this is not "tokens only": it is "something, always". Without a
        # subject there is nothing to partition state by, and the model must
        # never be reached - and paid for - by an unidentified caller.
        require_bearer_token=True,
        api_key_resolver=api_key_resolver,
        descriptor_registry=DescriptorRegistry(
            [_descriptor(composition, jwt_validation=jwt_validation, api_key_resolver=api_key_resolver)]
        ),
        # Discovery carries its own authentication flag, defaulting to open.
        # Listing the agent also lists every capability description, which is a
        # map of what the wiki can be made to do: it is not public.
        discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
    )
    return app


def _refuse_an_open_service(http: WikiAgentHttpSettings) -> None:
    """Fail loudly when nothing would identify a caller."""
    if http.uses_oidc or http.api_key:
        return
    raise WikiServiceConfigurationError(
        "the Wiki Agent HTTP service needs a caller: set WIKI_AGENT_HTTP_OIDC_ISSUER "
        "for a real deployment, or WIKI_AGENT_HTTP_API_KEY for a single-caller demonstration"
    )


def _closing(
    conversations: ConversationRuntimeCache[WikiConversation],
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Release every open MCP session when the service stops.

    Conversations hold live connections, so a process that exits without
    closing them leaves sockets to be reaped by the operating system and,
    against a real Confluence, sessions that look active long after they are
    not.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await conversations.aclose()

    return lifespan


def _descriptor(
    composition: WikiAgentCompositionRoot,
    *,
    jwt_validation: JwtValidationConfig | None,
    api_key_resolver: StaticApiKeyUserResolver | None,
) -> AgentDescriptor:
    """Describe the agent from the configuration it was built with.

    The authentication is read from the very values the endpoints are configured
    with, so a descriptor cannot claim a scheme this service refuses.
    """
    return WikiAgentDescriptorFactory(
        composition.manifest(),
        security=AdvertisedSecurity.of(jwt_validation=jwt_validation, api_key_resolver=api_key_resolver),
        agent_id=AGENT_ID,
    ).build()


def _jwt_validation(http: WikiAgentHttpSettings) -> JwtValidationConfig | None:
    """Build the token validation an OIDC deployment needs.

    Returning nothing when no issuer is configured is what keeps the API-key
    demonstration usable: the runtime then has no JWT authenticator to try.
    """
    if not http.uses_oidc:
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
    http: WikiAgentHttpSettings,
    settings: WikiAgentSettings,
) -> StaticApiKeyUserResolver | None:
    """Map the demonstration key onto the configured local user.

    One key, one caller, stated in configuration. It exists so the LibreChat
    integration can be proved before a realm exists, and it is refused outright
    once an issuer is configured.

    No e-mail address is supplied. A wiki account is identified by its subject,
    and asserting an address nobody verified would put an untrue claim into
    every audit record this caller produces.
    """
    if not http.api_key:
        return None
    if http.uses_oidc:
        _logger.warning("an OIDC issuer is configured; the static API key is ignored")
        return None
    return StaticApiKeyUserResolver(
        {
            http.api_key: ResolvedUser(
                user_id=settings.user_id,
                name=settings.user_id,
            )
        }
    )
