"""Build the configured chat model for Wiki Agent hosts."""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.langgraph.chat_model import AzureOpenAIRoute, LangGraphChatModelFactory
from ai_agent_lab.wiki.infrastructure.configuration.environment import WikiEnvironmentFile
from ai_agent_lab.wiki.infrastructure.configuration.settings import ChatModelSettings, ChatProvider

_logger = logging.getLogger(__name__)


def build_chat_model() -> BaseChatModel:
    """Build the configured chat model, OpenAI or Azure OpenAI."""
    WikiEnvironmentFile().load()
    settings = ChatModelSettings()
    factory = LangGraphChatModelFactory()
    _logger.info("Building chat model for provider '%s'...", settings.provider.value)
    if settings.provider is ChatProvider.AZURE_OPENAI:
        return factory.azure_openai(
            AzureOpenAIRoute(
                model=settings.azure_model,
                endpoint=settings.azure_endpoint,
                api_version=settings.azure_api_version,
            ),
            credential=AzureIdentityCredentialProvider().create_or_none(settings.azure_credential),
        )
    return factory.openai(model=settings.openai_model)
