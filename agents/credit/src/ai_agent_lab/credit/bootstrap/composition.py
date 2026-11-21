"""Local composition root: runtime configuration/transport and optional native MAF."""

import os
from pathlib import Path
from typing import Any

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.configuration.environment import EnvironmentFile
from ygo74.agent_runtime.domains.configuration.manifests import AgentManifestLoader, SkillManifestLoader
from ygo74.agent_runtime.domains.contracts.invocation_context import AgentInvocationContext, AgentInvocationContextScope
from ygo74.agent_runtime.domains.humanapproval.confirmation import (
    ConfiguredConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ygo74.agent_runtime.domains.mcp.binding import McpConnection, McpServerBinding
from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode, McpServerConfigurationLoader
from ygo74.agent_runtime.domains.mcp.oauth import McpOAuthProviderFactory
from ygo74.agent_runtime.domains.security.floor import SecurityFloor
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.credit.adapters.capabilities.registry import IDENTIFY_PERMISSION, CreditResultRenderer, build_registry
from ai_agent_lab.credit.application.skills.identification import IdentificationSkill
from ai_agent_lab.credit.domain.models import IdentificationResult
from ai_agent_lab.credit.infrastructure.configuration.settings import CreditCapability, CreditSettings
from ai_agent_lab.credit.infrastructure.mcp.client import EdgarMcpAdapter, McpGateway, RuntimeSessionProvider


class CreditApplication:
    """One local execution scope; no candidate or model session persistence."""

    def __init__(self, config: Path | None = None) -> None:
        """Load trusted configuration and construct lazy connections without SEC calls."""
        EnvironmentFile().load()
        directory = ConfigurationDirectory(config) if config else ConfigurationDirectory.resolve()
        floor = SecurityFloor(())
        manifests = SkillManifestLoader(PermissionRegistry((IDENTIFY_PERMISSION,)), floor)
        self.manifest = AgentManifestLoader(directory, manifests).load("credit")
        self.settings = CreditSettings.load(directory.require("agents", "credit", "settings.yaml"))
        configured = McpServerConfigurationLoader(CreditCapability).load(directory.require("mcp", "edgartools.yaml"))
        binding = configured.binding
        if binding.capabilities != frozenset((CreditCapability.IDENTIFY_COMPANY,)):
            raise ValueError("credit MCP binding must declare only identify_company")
        expected_tools = {"edgar_search": "edgar_search", "edgar_company": "edgar_company"}
        if dict(binding.tools) != expected_tools or binding.dialect != "edgartools-6.3":
            raise ValueError("credit MCP binding must use the verified official EdgarTools dialect")
        env = dict(binding.env)
        # SEC identity belongs to infrastructure and is only passed to the MCP subprocess.
        for key in ("EDGAR_IDENTITY", "EDGAR_LOCAL_DATA_DIR", "EDGAR_RATE_LIMIT_PER_SEC"):
            if key in os.environ:
                env[key] = os.environ[key]
        bound = McpServerBinding(
            server=binding.server,
            transport=binding.transport,
            capabilities=binding.capabilities,
            tools=binding.tools,
            dialect=binding.dialect,
            url=binding.url,
            command=os.environ.get("CREDIT_MCP_COMMAND") or binding.command,
            args=binding.args,
            env=env,
        )
        auth = None
        if configured.authentication_mode == McpAuthenticationMode.OAUTH and configured.oauth:
            auth = McpOAuthProviderFactory().build(binding.url, configured.oauth)
        if configured.authentication_mode == McpAuthenticationMode.OAUTH_ON_BEHALF_OF:
            raise ValueError("delegated authentication is outside local credit execution")
        connection = McpConnection(
            bound,
            timeout_seconds=configured.request_timeout_seconds,
            auth=auth,
            headers=configured.headers,
            network=configured.network,
            retry_settings=configured.retry_settings,
            circuit_breaker_settings=configured.circuit_breaker_settings,
        )
        self.gateway = McpGateway(
            RuntimeSessionProvider(connection),
            timeout=configured.request_timeout_seconds,
            max_attempts=self.settings.max_attempts,
            retry_delay=self.settings.retry_delay,
        )
        self.skill = IdentificationSkill(EdgarMcpAdapter(self.gateway, search_limit=self.settings.search_limit))
        self.registry = build_registry(self.manifest, self.skill)
        self.user = UserContext(
            user_id="local-analyst", session_id="local", permissions=frozenset((IDENTIFY_PERMISSION,))
        )
        self.policy = ConfiguredConfirmationPolicy(InMemoryConfirmationPreferenceStore(), floor)

    async def identify(self, payload: dict[str, object], correlation: str) -> IdentificationResult:
        """Execute structured identification under runtime correlation without a model."""
        with AgentInvocationContextScope.bind(AgentInvocationContext(request_id=correlation)):
            return await self.skill.execute(payload)

    def native_agent(self, client: Any = None) -> Any:
        """Build native MAF behavior with an injectable model client for offline tests."""
        from ai_agent_lab.maf.chat_client import AzureOpenAIRoute, MafChatClientFactory
        from ai_agent_lab.maf.registered_agent import create_registered_agent

        if client is None:
            factory = MafChatClientFactory()
            if self.settings.model_provider == "azure_openai":
                client = factory.azure_openai(
                    AzureOpenAIRoute(
                        model=self.settings.model,
                        endpoint=self.settings.azure_endpoint,
                        api_version=self.settings.azure_api_version,
                    )
                )
            else:
                client = factory.openai(model=self.settings.model)
        return create_registered_agent(
            client=client,
            name=self.manifest.name,
            instructions=self.manifest.instructions,
            registry=self.registry,
            renderer=CreditResultRenderer(),
            policy=self.policy,
            user=self.user,
        )

    async def aclose(self) -> None:
        """Release runtime MCP resources regardless of execution success."""
        await self.gateway.aclose()
