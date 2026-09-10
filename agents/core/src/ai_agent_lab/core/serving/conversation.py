"""What a serving surface needs from an agent, and nothing more.

An HTTP surface should not know which agentic framework answers it, and an agent
should not know which protocol carried the question. Between the two sits one
port: a turn goes in, a reply comes out.

Keeping it this narrow is what makes the framework comparison honest. Microsoft
Agent Framework, LangChain and CrewAI each provide an implementation; everything
in front of it - identity, transport, session isolation - is written once and
measured once, so a benchmark compares the frameworks rather than three
home-grown web layers.

Nothing here imports a framework, a transport or an agent. That is checked by the
architecture tests rather than left to good intentions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ai_agent_lab.core.security.principal import Principal


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One question, from an identified person, in a named conversation.

    Attributes:
        principal: Who is asking. Established by the transport, never by the
            message, and never carrying a credential.
        conversation_id: What this turn continues. Supplied by the caller, so it
            is a routing handle rather than a permission: it selects state only
            once combined with the authenticated subject.
        message: What the person wrote, verbatim.
    """

    principal: Principal
    conversation_id: str
    message: str

    @property
    def key(self) -> tuple[str, str]:
        """The pair that identifies this conversation's state.

        The subject comes first because it is the part that was authenticated:
        no conversation identifier can reach state belonging to someone else.
        """
        return (self.principal.subject, self.conversation_id)


@dataclass(frozen=True, slots=True)
class AgentReply:
    """What the agent answered, and what it left waiting.

    Attributes:
        text: The answer, as the person should read it.
        pending_confirmations: Identifiers of operations described but *not*
            performed, awaiting an explicit answer. Empty means nothing is
            waiting - never that everything succeeded.
    """

    text: str
    pending_confirmations: tuple[str, ...] = ()

    @property
    def awaits_confirmation(self) -> bool:
        """Whether this turn left something unperformed on purpose."""
        return bool(self.pending_confirmations)


@runtime_checkable
class ConversationEngine(Protocol):
    """Answers one turn of a conversation."""

    async def respond(self, turn: ConversationTurn) -> AgentReply:
        """Return the agent's answer to a turn."""
        ...
