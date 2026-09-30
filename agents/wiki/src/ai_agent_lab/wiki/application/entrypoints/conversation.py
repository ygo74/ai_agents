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

from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.humanapproval.confirmed_operations import ConfirmedOperationRunner
from ygo74.agent_runtime.domains.humanapproval.pending_renderer import PendingConfirmationRenderer
from ygo74.agent_runtime.domains.humanapproval.tickets import InMemoryPendingConfirmationStore
from ygo74.agent_runtime.domains.sessions.agent_conversation import (
    AgentConversation,
    HttpConversationEngine,
)

from ai_agent_lab.langgraph.approval import LangGraphApprovalTranslator
from ai_agent_lab.wiki.application.approval.tickets import WikiTicketApprovalResolver
from ai_agent_lab.wiki.application.composition import WikiAgentCompositionRoot, WikiAgentRuntime
from ai_agent_lab.wiki.application.session import WikiAgentSession
from ai_agent_lab.wiki.capabilities.results import WikiToolResultRenderer

WikiConversation = AgentConversation[WikiAgentRuntime, WikiAgentSession]
WikiConversationEngine = HttpConversationEngine[WikiConversation]


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
