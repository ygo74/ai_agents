"""Authenticated OpenAI HTTP composition; routes and lifecycle belong to the runtime."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from ygo74.agent_runtime.domains.configuration.agent_http_configuration import AgentHttpSettingsBuilder
from ygo74.agent_runtime.domains.configuration.agent_http_settings import AgentHttpSettings
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.contracts.agent_definition import AgentDefinition
from ygo74.agent_runtime.domains.discovery.discovery_configuration import DiscoveryConfiguration
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity, AgentDescriptorFactory
from ygo74.agent_runtime.domains.endpoints.managed_worker import ManagedAgentWorker, WorkerSettings
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.credit.bootstrap.composition import CreditApplication, load_manifest
from ai_agent_lab.credit.bootstrap.conversation import CreditConversationFactory
from ai_agent_lab.credit.infrastructure.configuration.environment import CreditEnvironmentFile

AGENT_ID = "corporate-credit-analyst"


def build_app(
    *, config: Path | None = None, env_file: Path | None = None, client: Any = None,
    application_factory: Callable[[UserContext], CreditApplication] | None = None,
) -> FastAPI:
    """Resolve authentication before admitting lazy caller-specific dependencies.

    Args:
        config: Delivered directory, or the runtime configuration environment setting.
        env_file: Optional selected environment file, preserved across reload workers.
        client: Optional native MAF model client for injected compositions.
        application_factory: Optional trusted application dependency factory.
    """
    CreditEnvironmentFile().load(env_file)
    directory = ConfigurationDirectory(config) if config else ConfigurationDirectory.resolve()
    manifest = load_manifest(directory)
    if manifest.http is None:
        raise ValueError("Credit agent manifest must declare an http section")
    # Resolve secrets and authentication without opening an MCP connection or model session.
    http = AgentHttpSettingsBuilder().build(manifest.http)
    limits = AgentHttpSettings.from_env("CREDIT_AGENT_HTTP_")
    descriptor = AgentDescriptorFactory(
        manifest, agent_id=AGENT_ID, tags=("credit", "sec"), owner="ai-agent-lab",
        created_at=datetime(2026, 11, 21, tzinfo=UTC),
        security=AdvertisedSecurity.of(jwt_validation=None, api_key_resolver=None,
                                      authenticators=http.authentication.authenticators),
    ).build()
    definition = AgentDefinition(
        descriptor, "ai_agent_lab.maf.registered_agent:create_registered_agent",
        require_email=False, tools=tuple(skill.operation for skill in manifest.skills),
        control_point="credit-deterministic-skill-gates",
    )
    security = manifest.http.security
    namespace = security.jwt.issuer if security.jwt else f"{AGENT_ID}:api-key"
    factory = CreditConversationFactory(config, client=client, application_factory=application_factory)
    worker = ManagedAgentWorker(definition, WorkerSettings(
        deployment_id=AGENT_ID, identity_namespace=namespace or AGENT_ID, http_settings=http,
        discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
        max_conversations=limits.max_conversations, idle_lifetime=limits.idle_lifetime(),
    ), factory.build)
    return worker.build_app(title="Corporate Credit Analyst")
