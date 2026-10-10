"""Standalone native Mail factory for trusted deployment configuration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from agent_framework import Agent
from ygo74.agent_runtime.domains.contracts.agent_definition import AgentFactoryContext

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.maf.chat_client import MafChatClientFactory
from ai_agent_lab.mail.application.chat_client import ConfiguredChatClientFactory
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.config.settings import ChatClientSettings, MailAgentSettings


@asynccontextmanager
async def create_agent(context: AgentFactoryContext) -> AsyncIterator[Agent]:
    """Yield the existing native Mail Agent, closing its MCP dependency scope.

    The local HTTP worker uses the advanced conversation factory to attach the
    ticket bridge and domain result renderer. This export also supports direct
    native use; callers must attach the approved Mail ticket/console bridge when
    hosting gated tools.
    """
    runtime = MailAgentCompositionRoot(
        MailAgentSettings(),
        ConfiguredChatClientFactory(
            ChatClientSettings(), MafChatClientFactory(), AzureIdentityCredentialProvider(),
        ).build(),
        principal=context.principal,
        base_path=Path.cwd(),
    ).build(session_id=context.conversation_id)
    try:
        yield runtime.agent
    finally:
        await runtime.aclose()
