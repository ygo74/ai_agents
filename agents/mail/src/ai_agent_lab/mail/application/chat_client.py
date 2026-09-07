"""Selection of the chat client from the configuration.

This is a composition concern: the configuration layer describes the provider
without knowing any framework, the framework adapter builds a client without
reading the environment, and this module joins the two.
"""

from __future__ import annotations

from agent_framework import SupportsChatGetResponse

from ai_agent_lab.maf.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.maf.chat_client import (
    AzureCredential,
    AzureOpenAIRoute,
    ChatClientConfigurationError,
    MafChatClientFactory,
)
from ai_agent_lab.mail.config.settings import (
    AzureCredentialMode,
    ChatClientSettings,
    ChatProvider,
)


class ConfiguredChatClientFactory:
    """Builds the chat client the configuration asks for."""

    def __init__(
        self,
        settings: ChatClientSettings,
        factory: MafChatClientFactory,
        credential_provider: AzureIdentityCredentialProvider,
    ) -> None:
        self._settings = settings
        self._factory = factory
        self._credential_provider = credential_provider

    def build(self) -> SupportsChatGetResponse:
        """Return the chat client of the configured provider."""
        if self._settings.provider is ChatProvider.AZURE_OPENAI:
            return self._factory.azure_openai(self._route(), credential=self._credential())
        return self._factory.openai(model=self._settings.openai_model)

    def _route(self) -> AzureOpenAIRoute:
        """Describe the configured Azure OpenAI deployment."""
        self._reject_ambiguous_route()
        return AzureOpenAIRoute(
            model=self._settings.azure_model,
            endpoint=self._settings.azure_endpoint,
            api_version=self._settings.azure_api_version,
        )

    def _reject_ambiguous_route(self) -> None:
        """Refuse a base URL, which the client cannot combine with an endpoint.

        Reporting it here keeps a stale configuration from surfacing as an
        opaque framework error.
        """
        if not self._settings.azure_base_url:
            return
        raise ChatClientConfigurationError(
            "AZURE_OPENAI_BASE_URL is not supported: put the URL in AZURE_OPENAI_ENDPOINT, "
            "which accepts a trailing /openai/v1"
        )

    def _credential(self) -> AzureCredential | None:
        """Return the Entra ID credential, or nothing when a key is used."""
        mode = self._settings.azure_credential
        if mode is AzureCredentialMode.API_KEY:
            return None
        return self._credential_provider.create(mode)
