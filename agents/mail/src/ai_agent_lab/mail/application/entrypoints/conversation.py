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
from dataclasses import dataclass

from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.contracts.conversation import AgentReply, ConversationTurn

from ai_agent_lab.core.security.commands import ConfirmationCommand, ConfirmationCommandParser
from ai_agent_lab.core.security.tickets import (
    ConfirmationTicket,
    InMemoryPendingConfirmationStore,
    PendingConfirmationStore,
    UnknownTicketError,
)
from ai_agent_lab.core.serving.confirmations import ConfirmedOperationRunner
from ai_agent_lab.core.serving.pending import PendingConfirmationRenderer
from ai_agent_lab.core.serving.runtimes import ConversationRuntimeCache
from ai_agent_lab.maf.approval import MafApprovalTranslator
from ai_agent_lab.mail.application.approval.tickets import TicketApprovalResolver
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot, MailAgentRuntime
from ai_agent_lab.mail.application.session import MailAgentSession
from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer

_UNKNOWN_TICKET = (
    "That confirmation is not awaiting an answer. It may have been answered "
    "already, or it may have expired. Ask again and a new one will be offered."
)
_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MailConversation:
    """Everything one conversation needs, for one authenticated caller."""

    runtime: MailAgentRuntime
    session: MailAgentSession
    store: PendingConfirmationStore
    runner: ConfirmedOperationRunner
    conversation_id: str
    renderer: PendingConfirmationRenderer

    async def aclose(self) -> None:
        """Release the MCP session this conversation holds."""
        _logger.info("Closing Mail Agent conversation")
        _logger.debug(
            "MailConversation.aclose arguments: conversation_id=%s, user_id=%s",
            self.conversation_id,
            self.runtime.user.user_id,
        )
        await self.runtime.aclose()

    def waiting(self) -> tuple[str, ...]:
        """Identifiers of the operations described but not performed."""
        _logger.info("Listing pending Mail Agent confirmations")
        _logger.debug(
            "MailConversation.waiting arguments: conversation_id=%s, user_id=%s",
            self.conversation_id,
            self.runtime.user.user_id,
        )
        pending = self._pending()
        _logger.info("Collecting identifiers from pending Mail Agent confirmations")
        return tuple(ticket.ticket_id for ticket in pending)

    def describe_pending(self) -> str:
        """Render what is waiting, so the answer can be given by name.

        Written by the application rather than by the model: what is pending is
        a fact about the ledger, and a model paraphrasing it could drop one.
        """
        _logger.info("Rendering pending Mail Agent confirmations")
        _logger.debug(
            "MailConversation.describe_pending arguments: conversation_id=%s, user_id=%s",
            self.conversation_id,
            self.runtime.user.user_id,
        )
        return self.renderer.render(self._pending())

    def _pending(self) -> tuple[ConfirmationTicket, ...]:
        """The tickets of this conversation, for its own caller."""
        _logger.info("Reading pending Mail Agent confirmations")
        _logger.debug(
            "MailConversation._pending arguments: conversation_id=%s, user_id=%s",
            self.conversation_id,
            self.runtime.user.user_id,
        )
        return self.store.pending(
            subject=self.runtime.user.user_id,
            conversation_id=self.conversation_id,
        )


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


class MailConversationEngine:
    """Answers one turn of a Mail Agent conversation."""

    def __init__(
        self,
        conversations: ConversationRuntimeCache[MailConversation],
        parser: ConfirmationCommandParser | None = None,
    ) -> None:
        _logger.info("Initializing Mail Agent conversation engine")
        _logger.debug(
            "MailConversationEngine.__init__ arguments: cache_type=%s, parser_type=%s",
            type(conversations).__name__,
            None if parser is None else type(parser).__name__,
        )
        self._conversations = conversations
        self._parser = parser or ConfirmationCommandParser()

    async def respond(self, turn: ConversationTurn) -> AgentReply:
        """Return the agent's answer, honouring a confirmation if that is what it is."""
        _logger.info("Responding to Mail Agent conversation turn")
        _logger.debug(
            "MailConversationEngine.respond arguments: subject=%s, conversation_id=%s, message_length=%d",
            turn.principal.subject,
            turn.conversation_id,
            len(turn.message),
        )
        conversation = await self._conversations.acquire(turn.principal, turn.conversation_id)

        command = self._parser.parse(turn.message)
        if command is not None:
            return await self._honour(conversation, command)

        text = await conversation.session.ask(turn.message)
        return self._reply(conversation, text)

    async def _honour(self, conversation: MailConversation, command: ConfirmationCommand) -> AgentReply:
        """Run what a claimed ticket describes, or report that there is none."""
        _logger.info("Handling Mail Agent confirmation command")
        _logger.debug(
            "MailConversationEngine._honour arguments: conversation_id=%s, command_type=%s, ticket_id=%s",
            conversation.conversation_id,
            type(command).__name__,
            command.ticket_id,
        )
        try:
            text = await conversation.runner.run(command)
        except UnknownTicketError:
            # Deliberately not an error response: the caller did nothing wrong,
            # and the conversation should carry on rather than fail.
            return self._reply(conversation, _UNKNOWN_TICKET)
        return self._reply(conversation, text)

    @staticmethod
    def _reply(conversation: MailConversation, text: str) -> AgentReply:
        """Attach what is still waiting to whatever was answered."""
        _logger.info("Building Mail Agent conversation reply")
        _logger.debug(
            "MailConversationEngine._reply arguments: conversation_id=%s, user_id=%s, text_length=%d",
            conversation.conversation_id,
            conversation.runtime.user.user_id,
            len(text),
        )
        return AgentReply(
            text=text + conversation.describe_pending(),
            pending_confirmations=conversation.waiting(),
        )
