"""One Mail Agent conversation, driven by requests rather than by a console.

This is where the pieces meet: a runtime built for an authenticated caller, a
session that resolves approvals into tickets, and a runner that honours a ticket
when the answer arrives in a later request.

The order of the two branches in :meth:`MailConversationEngine.respond` is a
security decision, not a convenience. A confirmation is recognised **before** the
model is given the turn, so an approval is never something a model can
reinterpret, rephrase or act upon. Anything that is not literally an answer to a
pending confirmation is an ordinary message and goes to the model as such.
"""

from __future__ import annotations

import logging

from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.humanapproval.confirmed_operations import ConfirmedOperationRunner
from ygo74.agent_runtime.domains.humanapproval.pending_renderer import PendingConfirmationRenderer
from ygo74.agent_runtime.domains.humanapproval.tickets import InMemoryPendingConfirmationStore
from ygo74.agent_runtime.domains.sessions.agent_conversation import (
    AgentConversation,
    HttpConversationEngine,
)

from ai_agent_lab.maf.approval import MafApprovalTranslator
from ai_agent_lab.mail.application.approval.tickets import TicketApprovalResolver
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot, MailAgentRuntime
from ai_agent_lab.mail.application.session import MailAgentSession
from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer

_logger = logging.getLogger(__name__)

MailConversation = AgentConversation[MailAgentRuntime, MailAgentSession]
MailConversationEngine = HttpConversationEngine[MailConversation]


class MailConversationFactory:
    """Builds a conversation for one caller.

    The composition root is handed the principal, so the mailbox, the
    preferences and the audit trail all follow the authenticated caller rather
    than a deployment-wide setting.
    """

    def __init__(
        self,
        composition: MailAgentCompositionRoot,
        renderer: PendingConfirmationRenderer | None = None,
    ) -> None:
        _logger.info("Initializing Mail Agent conversation factory")
        _logger.debug(
            "MailConversationFactory.__init__ arguments: composition_type=%s, renderer_type=%s",
            type(composition).__name__,
            None if renderer is None else type(renderer).__name__,
        )
        self._composition = composition
        self._renderer = renderer or PendingConfirmationRenderer()

    async def build(self, principal: AgentPrincipal, conversation_id: str) -> MailConversation:
        """Assemble the conversation of one caller."""
        _logger.info("Building Mail Agent conversation")
        _logger.debug(
            "MailConversationFactory.build arguments: subject=%s, conversation_id=%s",
            principal.subject,
            conversation_id,
        )
        runtime = self._composition.for_principal(principal).build(session_id=conversation_id)
        store = InMemoryPendingConfirmationStore()
        session = MailAgentSession(
            runtime,
            TicketApprovalResolver(runtime.presenter, store, runtime.user, conversation_id=conversation_id),
            MafApprovalTranslator(),
        )
        runner = ConfirmedOperationRunner(
            runtime.registry,
            store,
            runtime.confirmation_ledger,
            MailToolResultRenderer(),
            runtime.user,
            conversation_id=conversation_id,
        )
        return MailConversation(
            runtime=runtime,
            session=session,
            store=store,
            runner=runner,
            conversation_id=conversation_id,
            renderer=self._renderer,
        )

    @staticmethod
    async def close(conversation: MailConversation) -> None:
        """Release a conversation the cache is evicting."""
        _logger.info("Closing evicted Mail Agent conversation")
        _logger.debug(
            "MailConversationFactory.close arguments: conversation_id=%s, user_id=%s",
            conversation.conversation_id,
            conversation.runtime.user.user_id,
        )
        await conversation.aclose()
