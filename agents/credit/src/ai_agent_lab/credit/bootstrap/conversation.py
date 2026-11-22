"""Compose caller-scoped Credit conversations using the shared MAF session."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.humanapproval.commands import ConfirmationCommand
from ygo74.agent_runtime.domains.humanapproval.pending_renderer import PendingConfirmationRenderer
from ygo74.agent_runtime.domains.humanapproval.tickets import InMemoryPendingConfirmationStore, UnknownTicketError
from ygo74.agent_runtime.domains.security.user_context import UserContext
from ygo74.agent_runtime.domains.sessions.agent_conversation import AgentConversation, ConfirmationRunnerPort
from ygo74.agent_runtime.integrations.agentframework.binding import AgentFrameworkSession

from ai_agent_lab.credit.adapters.capabilities.registry import IDENTIFY_PERMISSION
from ai_agent_lab.credit.bootstrap.composition import CreditApplication

CreditConversation = AgentConversation[CreditApplication, AgentFrameworkSession]


class CreditConfirmationRunner(ConfirmationRunnerPort):
    """Refuse confirmation commands: issuer identification has no write operations."""

    async def run(self, command: ConfirmationCommand) -> str:
        """Reject a ticket that cannot exist in this read-only agent.

        Args:
            command: Parsed command; no operation can be authorized by its text.
        """
        raise UnknownTicketError(command.ticket_id)


class CreditConversationFactory:
    """Build one native session and MCP resource scope per verified caller/conversation."""

    def __init__(
        self, config: Path | None, *, client: Any = None,
        application_factory: Callable[[UserContext], CreditApplication] | None = None,
    ) -> None:
        """Accept operator configuration and optional injected application/model dependencies.

        Args:
            config: Delivered configuration directory.
            client: Native MAF model client; None selects configured OpenAI/Azure.
            application_factory: Trusted dependency injection override, never a request field.
        """
        self._config = config
        self._client = client
        self._application_factory = application_factory

    async def build(self, principal: AgentPrincipal, conversation_id: str) -> CreditConversation:
        """Grant the public read capability to an authenticated analyst and compose its session.

        Args:
            principal: Identity established by endpoint authentication.
            conversation_id: Caller-scoped handle leased by the runtime cache.
        """
        # The deployment admits authenticated analysts to public SEC identification.
        # Neither request body fields nor model output supply identity or permissions.
        user = UserContext(user_id=principal.subject, session_id=conversation_id,
                           permissions=frozenset((IDENTIFY_PERMISSION,)))
        application = (self._application_factory(user) if self._application_factory else
                       CreditApplication(self._config, user=user, load_environment=False))
        try:
            session = AgentFrameworkSession(application.native_agent(self._client), session_id=conversation_id,
                                            tool_names=("identify_company",))
            return CreditConversation(application, session, InMemoryPendingConfirmationStore(),
                                      CreditConfirmationRunner(), conversation_id, PendingConfirmationRenderer())
        except BaseException:
            # The cache cannot own a failed construction; close its MCP dependencies here.
            await application.aclose()
            raise
