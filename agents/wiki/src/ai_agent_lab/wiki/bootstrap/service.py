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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from langchain_core.language_models import BaseChatModel
from ygo74.agent_runtime.domains.auth.apikey_authenticator import StaticApiKeyUserResolver
from ygo74.agent_runtime.domains.auth.auth_context import ResolvedUser
from ygo74.agent_runtime.domains.auth.authentication_policy import AuthenticationPolicy
from ygo74.agent_runtime.domains.auth.jwt_authenticator import (
    DiscoveredJwksKeyResolver,
    JwksKeyResolver,
    JwtValidationConfig,
)
from ygo74.agent_runtime.domains.auth.oidc_discovery import OidcDiscovery
from ygo74.agent_runtime.domains.contracts.agent_definition import AgentDefinition, AgentFactoryContext
from ygo74.agent_runtime.domains.discovery.agent_descriptor import AgentDescriptor
from ygo74.agent_runtime.domains.discovery.discovery_configuration import DiscoveryConfiguration
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity
from ygo74.agent_runtime.domains.endpoints.hosting_factory import EndpointSurface
from ygo74.agent_runtime.domains.endpoints.managed_worker import WorkerSettings
from ygo74.agent_runtime.domains.http.asgi_lifecycle import AsgiShutdownRegistrar
from ygo74.agent_runtime.domains.http.client_lifecycle import SyncHttpClientOwner
from ygo74.agent_runtime.integrations.langchain import LangGraphRunnable
from ygo74.agent_runtime.integrations.langchain.worker import LangGraphWorker

from ai_agent_lab.core.observability.logging_config import setup_logging
from ai_agent_lab.wiki.adapters.http.entrypoint import WikiAgentDescriptorFactory
from ai_agent_lab.wiki.bootstrap.chat_model import build_chat_model
from ai_agent_lab.wiki.bootstrap.composition import WikiAgentCompositionRoot
from ai_agent_lab.wiki.bootstrap.conversation import WikiConversationFactory
from ai_agent_lab.wiki.infrastructure.configuration.environment import WikiEnvironmentFile
from ai_agent_lab.wiki.infrastructure.configuration.http_settings import WikiAgentHttpSettings
from ai_agent_lab.wiki.infrastructure.configuration.settings import WikiAgentSettings

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
    env_file: Path | None = None,
) -> FastAPI:
    """Assemble the HTTP service from the environment."""
    WikiEnvironmentFile().load(env_file)
    settings = WikiAgentSettings()
    http = WikiAgentHttpSettings.load()
    setup_logging(default_level=settings.log_level)

    _refuse_an_open_service(http)

    composition = WikiAgentCompositionRoot(
        settings,
        chat_model or build_chat_model(),
        base_path=base_path or Path.cwd(),
    )
    factory = WikiConversationFactory(composition)

    # Computed once and used twice: the authenticator chain is configured from
    # these, and the descriptor is derived from them, so discovery cannot
    # advertise a scheme this service does not accept.
    oidc_http = SyncHttpClientOwner() if http.uses_oidc else None
    jwt_validation = _jwt_validation(http, oidc_http)
    api_key_resolver = _api_key_resolver(http, settings)

    if jwt_validation is not None:
        authentication = AuthenticationPolicy.jwt(jwt_validation)
    elif api_key_resolver is not None:
        authentication = AuthenticationPolicy.api_key(api_key_resolver)
    else:
        raise WikiServiceConfigurationError("the Wiki Agent HTTP service needs a caller")

    descriptor = _descriptor(
        composition,
        jwt_validation=jwt_validation,
        api_key_resolver=api_key_resolver,
    )
    definition = AgentDefinition(
        descriptor=descriptor,
        factory="ai_agent_lab.wiki.bootstrap.service:build_graph",
        tools=tuple(skill.operation for skill in composition.manifest().skills),
        control_point="wiki-confirmation-policy",
    )
    app = LangGraphWorker(
        definition,
        WorkerSettings(
            deployment_id="wiki-agent",
            identity_namespace=http.oidc_issuer or "wiki-api-key",
            authentication=authentication,
            surfaces=(EndpointSurface.OPENAI_CHAT_COMPLETIONS,),
            discovery=DiscoveryConfiguration(
                enable_openai_models=True,
                require_authentication=True,
            ),
            max_conversations=http.max_conversations,
            idle_lifetime=http.idle_lifetime(),
        ),
        conversation_factory=factory.build,
    ).build_app()
    if oidc_http is not None:
        AsgiShutdownRegistrar.register(app, oidc_http.close, startup=oidc_http.start)
    return app


@asynccontextmanager
async def build_graph(context: AgentFactoryContext) -> AsyncIterator[LangGraphRunnable]:
    """Build and scope a Wiki graph for a verified caller and conversation.

    The managed worker uses the advanced conversation factory so Wiki can attach
    ticket and ledger handling. This export remains the genuine simple graph
    factory named by the shared deployment definition.
    """
    composition = WikiAgentCompositionRoot(
        WikiAgentSettings(),
        build_chat_model(),
        principal=context.principal,
    )
    runtime = composition.build(session_id=context.conversation_id)
    try:
        yield runtime.agent
    finally:
        await runtime.aclose()


def _refuse_an_open_service(http: WikiAgentHttpSettings) -> None:
    """Fail loudly when nothing would identify a caller."""
    if http.uses_oidc or http.api_key:
        return
    raise WikiServiceConfigurationError(
        "the Wiki Agent HTTP service needs a caller: set WIKI_AGENT_HTTP_OIDC_ISSUER "
        "for a real deployment, or WIKI_AGENT_HTTP_API_KEY for a single-caller demonstration"
    )


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


def _jwt_validation(
    http: WikiAgentHttpSettings,
    http_client_owner: SyncHttpClientOwner | None = None,
) -> JwtValidationConfig | None:
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
        key_resolver=(
            JwksKeyResolver(
                jwks_url=http.jwks_url_override,
                http_client_owner=http_client_owner,
                service_identity=http.oidc_issuer,
            )
            if http.jwks_url_override
            else DiscoveredJwksKeyResolver(
                issuer=http.oidc_issuer,
                discovery=OidcDiscovery(http_client_owner=http_client_owner),
            )
        ),
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
