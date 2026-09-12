"""One Wiki Agent conversation, driven by requests rather than by a console.

This is where the pieces meet: a runtime built for an authenticated caller, a
session that resolves approvals into tickets, and a runner that honours a ticket
when the answer arrives in a later request.

The order of the two branches in :meth:`WikiConversationEngine.respond` is a
security decision, not a convenience. A confirmation is recognised **before** the
model is given the turn, so an approval is never something a model can
reinterpret, rephrase or act upon. Anything that is not literally an answer to a
pending confirmation is an ordinary message and goes to the model as such.

Isolation is doubly enforced here, and both halves matter. The runtime cache keys
state by the authenticated subject first, and the LangGraph thread identifier is
hashed from that subject together with the conversation, so the half a caller
controls is only ever half.
"""

from __future__ import annotations

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
from ai_agent_lab.langgraph.approval import LangGraphApprovalTranslator
from ai_agent_lab.wiki.application.approval.tickets import WikiTicketApprovalResolver
from ai_agent_lab.wiki.application.composition import WikiAgentCompositionRoot, WikiAgentRuntime
from ai_agent_lab.wiki.application.session import WikiAgentSession
from ai_agent_lab.wiki.capabilities.results import WikiToolResultRenderer

_UNKNOWN_TICKET = (
    "That confirmation is not awaiting an answer. It may have been answered "
    "already, or it may have expired. Ask again and a new one will be offered."
)


@dataclass(frozen=True, slots=True)
class WikiConversation:
    """Everything one conversation needs, for one authenticated caller."""

    runtime: WikiAgentRuntime
    session: WikiAgentSession
    store: PendingConfirmationStore
    runner: ConfirmedOperationRunner
    conversation_id: str
    renderer: PendingConfirmationRenderer

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
        return self.renderer.render(self._pending())

    def _pending(self) -> tuple[ConfirmationTicket, ...]:
        """The tickets of this conversation, for its own caller."""
        return self.store.pending(
            subject=self.runtime.user.user_id,
            conversation_id=self.conversation_id,
        )


class WikiConversationFactory:
    """Builds a conversation for one caller.

    The composition root is handed the principal, so the wiki connection, the
    preferences and the audit trail all follow the authenticated caller rather
    than a deployment-wide setting. Over a per-user MCP binding that is what
    makes the agent respect the page and space restrictions of the person
    asking, instead of quietly reading around them.
    """

    def __init__(
        self,
        composition: WikiAgentCompositionRoot,
        renderer: PendingConfirmationRenderer | None = None,
    ) -> None:
        self._composition = composition
        self._renderer = renderer or PendingConfirmationRenderer()

    async def build(self, principal: AgentPrincipal, conversation_id: str) -> WikiConversation:
        """Assemble the conversation of one caller."""
        runtime = self._composition.for_principal(principal).build(session_id=conversation_id)
        store = InMemoryPendingConfirmationStore()
        session = WikiAgentSession(
            runtime,
            WikiTicketApprovalResolver(
                runtime.presenter,
                store,
                runtime.user,
                conversation_id=conversation_id,
            ),
            LangGraphApprovalTranslator(),
        )
        runner = ConfirmedOperationRunner(
            runtime.registry,
            store,
            runtime.confirmation_ledger,
            WikiToolResultRenderer(),
            runtime.user,
            conversation_id=conversation_id,
        )
        return WikiConversation(
            runtime=runtime,
            session=session,
            store=store,
            runner=runner,
            conversation_id=conversation_id,
            renderer=self._renderer,
        )

    @staticmethod
    async def close(conversation: WikiConversation) -> None:
        """Release a conversation the cache is evicting."""
        await conversation.aclose()


class WikiConversationEngine:
    """Answers one turn of a Wiki Agent conversation."""

    def __init__(
        self,
        conversations: ConversationRuntimeCache[WikiConversation],
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

    async def _honour(self, conversation: WikiConversation, command: ConfirmationCommand) -> AgentReply:
        """Run what a claimed ticket describes, or report that there is none."""
        try:
            text = await conversation.runner.run(command)
        except UnknownTicketError:
            # Deliberately not an error response: the caller did nothing wrong,
            # and the conversation should carry on rather than fail.
            return self._reply(conversation, _UNKNOWN_TICKET)
        return self._reply(conversation, text)

    @staticmethod
    def _reply(conversation: WikiConversation, text: str) -> AgentReply:
        """Attach what is still waiting to whatever was answered."""
        return AgentReply(
            text=text + conversation.describe_pending(),
            pending_confirmations=conversation.waiting(),
        )
