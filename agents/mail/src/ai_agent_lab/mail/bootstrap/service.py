"""Composition of the Mail Agent HTTP service.

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
from pathlib import Path

from fastapi import FastAPI
from ygo74.agent_runtime.domains.configuration.agent_http_configuration import (
    AgentHttpRuntimeSettings,
    AgentHttpSettingsBuilder,
)
from ygo74.agent_runtime.domains.contracts.agent_definition import AgentDefinition
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.discovery.agent_descriptor import AgentDescriptor
from ygo74.agent_runtime.domains.discovery.discovery_configuration import DiscoveryConfiguration
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity
from ygo74.agent_runtime.domains.endpoints.managed_worker import ManagedAgentWorker, WorkerSettings

from ai_agent_lab.core.observability.logging_config import setup_logging
from ai_agent_lab.mail.adapters.http.entrypoint import (
    MailAgentDescriptorFactory,
)
from ai_agent_lab.mail.bootstrap.conversation import (
    MailConversationFactory,
)
from ai_agent_lab.mail.bootstrap.factory import MailAgentApplicationFactory
from ai_agent_lab.mail.infrastructure.configuration.environment import MailEnvironmentFile
from ai_agent_lab.mail.infrastructure.configuration.http_settings import MailAgentHttpSettings
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentSettings

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


def build_app(*, base_path: Path | None = None, env_file: Path | None = None) -> FastAPI:
    """Assemble the HTTP service from the environment."""
    MailEnvironmentFile().load(env_file)
    settings = MailAgentSettings()
    http = MailAgentHttpSettings.load()
    setup_logging(default_level=settings.log_level)
    _logger.info("Building Mail Agent HTTP service")
    _logger.debug("build_app arguments: base_path=%s", base_path)

    composition = MailAgentApplicationFactory().build_composition(
        settings=settings,
        base_path=base_path,
    )
    factory = MailConversationFactory(composition)
    manifest = composition.manifest()
    http_runtime = _runtime_http_settings(manifest)

    definition = AgentDefinition(
        _descriptor(manifest, http_runtime),
        "ai_agent_lab.mail.adapters.maf.native:create_agent",
        require_email=True,
        tools=tuple(skill.operation for skill in manifest.skills),
        control_point="mail-deterministic-skill-gates",
    )
    worker = ManagedAgentWorker(
        definition,
        WorkerSettings(
            deployment_id=AGENT_ID,
            identity_namespace=_identity_namespace(manifest),
            http_settings=http_runtime,
            discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
            max_conversations=http.max_conversations,
            idle_lifetime=http.idle_lifetime(),
        ),
        factory.build,
    )
    return worker.build_app(title="Mail Agent")


def _runtime_http_settings(manifest: AgentManifest) -> AgentHttpRuntimeSettings:
    """Resolve the declared HTTP policy and fail without exposing secret values."""
    if manifest.http is None:
        raise MailServiceConfigurationError(
            "config/agents/mail/agent.yaml must declare an http section"
        )
    try:
        return AgentHttpSettingsBuilder().build(manifest.http)
    except ValueError as error:
        raise MailServiceConfigurationError(
            f"invalid HTTP settings in the Mail Agent manifest: {error}"
        ) from error


def _descriptor(
    manifest: AgentManifest,
    http_runtime: AgentHttpRuntimeSettings,
) -> AgentDescriptor:
    """Describe the exact authentication policy registered by the HTTP host."""
    _logger.info("Building Mail Agent HTTP descriptor")
    return MailAgentDescriptorFactory(
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
        raise MailServiceConfigurationError(
            "config/agents/mail/agent.yaml must declare an http section"
        )
    jwt = configuration.security.jwt
    if jwt is not None:
        return jwt.issuer or jwt.jwks_url or f"{AGENT_ID}:jwt"
    api_key = configuration.security.api_key
    if api_key is None:
        raise MailServiceConfigurationError("the Mail Agent manifest has no HTTP identity")
    return f"{AGENT_ID}:{api_key.user.subject}"
