"""Composition of the Wiki Agent HTTP service.

Everything the application owns is assembled here: which caller a request is
attributed to, which conversation it continues, and what is done with a gated
operation. Everything the transport owns - routes, OpenAI payload shapes, JWT
validation, discovery - comes from ``ygo74-agent-runtime``.

Authentication and routes come from the delivered ``agent.yaml`` manifest.
Secret values are resolved from environment-variable references only when the
HTTP host is built; conversation capacity and idle lifetime remain operator
settings.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from langchain_core.language_models import BaseChatModel
from ygo74.agent_runtime.domains.configuration.agent_http_configuration import (
    AgentHttpRuntimeSettings,
    AgentHttpSettingsBuilder,
)
from ygo74.agent_runtime.domains.contracts.agent_definition import AgentDefinition, AgentFactoryContext
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.discovery.agent_descriptor import AgentDescriptor
from ygo74.agent_runtime.domains.discovery.discovery_configuration import DiscoveryConfiguration
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity
from ygo74.agent_runtime.domains.endpoints.managed_worker import WorkerSettings
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

    composition = WikiAgentCompositionRoot(
        settings,
        chat_model or build_chat_model(),
        base_path=base_path or Path.cwd(),
    )
    factory = WikiConversationFactory(composition)
    manifest = composition.manifest()
    http_runtime = _runtime_http_settings(manifest)

    descriptor = _descriptor(manifest, http_runtime)
    definition = AgentDefinition(
        descriptor=descriptor,
        factory="ai_agent_lab.wiki.bootstrap.service:build_graph",
        tools=tuple(skill.operation for skill in manifest.skills),
        control_point="wiki-confirmation-policy",
    )
    return LangGraphWorker(
        definition,
        WorkerSettings(
            deployment_id="wiki-agent",
            identity_namespace=_identity_namespace(manifest),
            http_settings=http_runtime,
            discovery=DiscoveryConfiguration(
                enable_openai_models=True,
                require_authentication=True,
            ),
            max_conversations=http.max_conversations,
            idle_lifetime=http.idle_lifetime(),
        ),
        conversation_factory=factory.build,
    ).build_app()


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


def _runtime_http_settings(manifest: AgentManifest) -> AgentHttpRuntimeSettings:
    """Resolve the declared HTTP policy and fail without exposing secret values."""
    if manifest.http is None:
        raise WikiServiceConfigurationError(
            "config/agents/wiki/agent.yaml must declare an http section"
        )
    try:
        return AgentHttpSettingsBuilder().build(manifest.http)
    except ValueError as error:
        raise WikiServiceConfigurationError(
            f"invalid HTTP settings in the Wiki Agent manifest: {error}"
        ) from error


def _descriptor(
    manifest: AgentManifest,
    http_runtime: AgentHttpRuntimeSettings,
) -> AgentDescriptor:
    """Describe the exact authentication policy registered by the HTTP host."""
    return WikiAgentDescriptorFactory(
        manifest,
        security=AdvertisedSecurity.of(
            jwt_validation=None,
            api_key_resolver=None,
            authenticators=http_runtime.authentication.authenticators
        ),
        agent_id=AGENT_ID,
    ).build()


def _identity_namespace(manifest: AgentManifest) -> str:
    """Partition cached conversations by the configured issuer or API-key subject."""
    configuration = manifest.http
    if configuration is None:
        raise WikiServiceConfigurationError(
            "config/agents/wiki/agent.yaml must declare an http section"
        )
    jwt = configuration.security.jwt
    if jwt is not None:
        return jwt.issuer or jwt.jwks_url or f"{AGENT_ID}:jwt"
    api_key = configuration.security.api_key
    if api_key is None:
        raise WikiServiceConfigurationError("the Wiki Agent manifest has no HTTP identity")
    return f"{AGENT_ID}:{api_key.user.subject}"
