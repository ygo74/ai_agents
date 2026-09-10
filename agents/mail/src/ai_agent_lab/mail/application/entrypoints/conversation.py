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

from dataclasses import dataclass

from ai_agent_lab.core.security.commands import ConfirmationCommand, ConfirmationCommandParser
from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.core.security.tickets import (
    ConfirmationTicket,
    InMemoryPendingConfirmationStore,
    PendingConfirmationStore,
    UnknownTicketError,
)
from ai_agent_lab.core.serving.conversation import AgentReply, ConversationTurn
from ai_agent_lab.core.serving.runtimes import ConversationRuntimeCache
from ai_agent_lab.maf.approval import MafApprovalTranslator
from ai_agent_lab.mail.application.approval.tickets import (
    ConfirmedOperationRunner,
    TicketApprovalResolver,
)
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot, MailAgentRuntime
from ai_agent_lab.mail.application.session import MailAgentSession
from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer

_UNKNOWN_TICKET = (
    "That confirmation is not awaiting an answer. It may have been answered "
    "already, or it may have expired. Ask again and a new one will be offered."
)


@dataclass(frozen=True, slots=True)
class MailConversation:
    """Everything one conversation needs, for one authenticated caller."""

    runtime: MailAgentRuntime
    session: MailAgentSession
    store: PendingConfirmationStore
    runner: ConfirmedOperationRunner
    conversation_id: str

    async def aclose(self) -> None:
        """Release the MCP session this conversation holds."""
        await self.runtime.aclose()

    def waiting(self) -> tuple[str, ...]:
        """Identifiers of the operations described but not performed."""
        return tuple(ticket.ticket_id for ticket in self._pending())

    def describe_pending(self) -> str:
        """Render what is waiting, so the answer can be given by name.

        Written by the application rather than by the model: what is pending is
        a fact about the ledger, and a model paraphrasing it could drop one.
        """
        waiting = self._pending()
        if not waiting:
            return ""
        lines = ["", "Awaiting your confirmation - nothing has been changed yet:"]
        lines.extend(f"  - {ticket.request.title} Reply: CONFIRM {ticket.ticket_id}" for ticket in waiting)
        return "\n".join(lines)

    def _pending(self) -> tuple[ConfirmationTicket, ...]:
        """The tickets of this conversation, for its own caller."""
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

    def __init__(self, composition: MailAgentCompositionRoot) -> None:
        self._composition = composition

    async def build(self, principal: Principal, conversation_id: str) -> MailConversation:
        """Assemble the conversation of one caller."""
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
        )

    @staticmethod
    async def close(conversation: MailConversation) -> None:
        """Release a conversation the cache is evicting."""
        await conversation.aclose()


class MailConversationEngine:
    """Answers one turn of a Mail Agent conversation."""

    def __init__(
        self,
        conversations: ConversationRuntimeCache[MailConversation],
        parser: ConfirmationCommandParser | None = None,
    ) -> None:
        self._conversations = conversations
        self._parser = parser or ConfirmationCommandParser()

    async def respond(self, turn: ConversationTurn) -> AgentReply:
        """Return the agent's answer, honouring a confirmation if that is what it is."""
        conversation = await self._conversations.acquire(turn.principal, turn.conversation_id)

        command = self._parser.parse(turn.message)
        if command is not None:
            return await self._honour(conversation, command)

        text = await conversation.session.ask(turn.message)
        return self._reply(conversation, text)

    async def _honour(self, conversation: MailConversation, command: ConfirmationCommand) -> AgentReply:
        """Run what a claimed ticket describes, or report that there is none."""
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
        return AgentReply(
            text=text + conversation.describe_pending(),
            pending_confirmations=conversation.waiting(),
        )
