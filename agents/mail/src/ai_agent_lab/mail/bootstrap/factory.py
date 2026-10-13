"""Shared construction of the Mail Agent composition root."""

from __future__ import annotations

from pathlib import Path

from agent_framework import SupportsChatGetResponse
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.maf.chat_client import MafChatClientFactory
from ai_agent_lab.mail.bootstrap.chat_client import ConfiguredChatClientFactory
from ai_agent_lab.mail.bootstrap.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.infrastructure.configuration.settings import ChatClientSettings, MailAgentSettings


class MailAgentApplicationFactory:
    """Build the Mail Agent composition consistently for each host."""

    def __init__(self, chat_client_factory: ConfiguredChatClientFactory | None = None) -> None:
        self._chat_client_factory = chat_client_factory

    def build_chat_client(self) -> SupportsChatGetResponse:
        """Build the configured framework chat client."""
        if self._chat_client_factory is None:
            self._chat_client_factory = ConfiguredChatClientFactory(
                ChatClientSettings(),
                MafChatClientFactory(),
                AzureIdentityCredentialProvider(),
            )
        return self._chat_client_factory.build()

    def build_composition(
        self,
        *,
        settings: MailAgentSettings | None = None,
        chat_client: SupportsChatGetResponse | None = None,
        principal: AgentPrincipal | None = None,
        base_path: Path | None = None,
    ) -> MailAgentCompositionRoot:
        """Build a composition root with one consistent set of dependencies."""
        return MailAgentCompositionRoot(
            settings if settings is not None else MailAgentSettings(),
            chat_client if chat_client is not None else self.build_chat_client(),
            principal=principal,
            base_path=base_path if base_path is not None else Path.cwd(),
        )
