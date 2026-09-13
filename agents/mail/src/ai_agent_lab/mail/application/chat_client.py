"""Selection of the chat client from the configuration.

This is a composition concern: the configuration layer describes the provider
without knowing any framework, the framework adapter builds a client without
reading the environment, and this module joins the two.
"""

from __future__ import annotations

import logging

from agent_framework import SupportsChatGetResponse

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
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

_logger = logging.getLogger(__name__)


class ConfiguredChatClientFactory:
    """Builds the chat client the configuration asks for."""

    def __init__(
        self,
        settings: ChatClientSettings,
        factory: MafChatClientFactory,
        credential_provider: AzureIdentityCredentialProvider,
    ) -> None:
        _logger.info("Initializing configured Mail Agent chat client factory")
        _logger.debug(
            "ConfiguredChatClientFactory.__init__ arguments: provider=%s, factory_type=%s, credential_provider_type=%s",
            settings.provider.value,
            type(factory).__name__,
            type(credential_provider).__name__,
        )
        self._settings = settings
        self._factory = factory
        self._credential_provider = credential_provider

    def build(self) -> SupportsChatGetResponse:
        """Return the chat client of the configured provider."""
        _logger.info("Building configured Mail Agent chat client")
        _logger.debug(
            "ConfiguredChatClientFactory.build arguments: provider=%s",
            self._settings.provider.value,
        )
        if self._settings.provider is ChatProvider.AZURE_OPENAI:
            return self._factory.azure_openai(self._route(), credential=self._credential())
        return self._factory.openai(model=self._settings.openai_model)

    def _route(self) -> AzureOpenAIRoute:
        """Describe the configured Azure OpenAI deployment."""
        _logger.info("Building Mail Agent Azure OpenAI route")
        _logger.debug(
            "ConfiguredChatClientFactory._route arguments: model=%s, endpoint_configured=%s, api_version=%s",
            self._settings.azure_model,
            bool(self._settings.azure_endpoint),
            self._settings.azure_api_version,
        )
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
        _logger.info("Validating Mail Agent Azure OpenAI route")
        _logger.debug(
            "ConfiguredChatClientFactory._reject_ambiguous_route arguments: base_url_configured=%s",
            bool(self._settings.azure_base_url),
        )
        if not self._settings.azure_base_url:
            return
        raise ChatClientConfigurationError(
            "AZURE_OPENAI_BASE_URL is not supported: put the URL in AZURE_OPENAI_ENDPOINT, "
            "which accepts a trailing /openai/v1"
        )

    def _credential(self) -> AzureCredential | None:
        """Return the Entra ID credential, or nothing when a key is used."""
        mode = self._settings.azure_credential
        _logger.info("Building Mail Agent Azure credential")
        _logger.debug(
            "ConfiguredChatClientFactory._credential arguments: credential_mode=%s",
            mode.value,
        )
        if mode is AzureCredentialMode.API_KEY:
            return None
        return self._credential_provider.create(mode)
