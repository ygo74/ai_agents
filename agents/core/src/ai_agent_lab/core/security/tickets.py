"""Confirmations that survive the end of a turn.

At a console the question is asked and the turn waits. An OpenAI-compatible API
has no such side channel: the request must be answered, so a pending approval
cannot block. The turn therefore ends having changed nothing, and the answer
arrives in a later request.

What is kept between the two is a :class:`ConfirmationTicket`. It holds both what
the person read *and the exact arguments the operation will run with*, which is
the point: replaying a ticket re-invokes the capability from stored arguments,
never from what a model says the second time. A model can therefore describe an
operation and be unable to alter it between the description and the execution.

Four properties make a ticket safe to hand out, and every one of them is enforced
when it is claimed rather than when it is issued:

* it belongs to one subject, so nobody can confirm another person's operation;
* it belongs to one conversation, so an answer cannot be replayed elsewhere;
* it can be claimed once, so one approval never authorises two executions;
* it expires, so an abandoned confirmation stops being usable.

A ticket identifier is not a credential. It authorises nothing on its own: the
subject is taken from the authenticated caller, never from the text that carries
the identifier.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from ai_agent_lab.core.security.confirmation import ConfirmationRequest
from ai_agent_lab.core.security.errors import SecurityError

TICKET_PREFIX = "cfm-"
DEFAULT_TICKET_LIFETIME = timedelta(minutes=15)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    """Return the current instant, always timezone-aware."""
    return datetime.now(UTC)


class TicketError(SecurityError):
    """Base class for failures to issue or claim a confirmation ticket."""


class UnknownTicketError(TicketError):
    """Raised when a ticket was never issued, already used, or has expired.

    The three cases share one message on purpose. Distinguishing them would tell
    an unauthenticated guesser which identifiers exist, and none of the three
    changes what the caller should do.
    """

    def __init__(self, ticket_id: str) -> None:
        super().__init__(f"confirmation {ticket_id!r} is not awaiting an answer")
        self.ticket_id = ticket_id


def new_ticket_id() -> str:
    """Return an unguessable identifier for a pending confirmation."""
    return f"{TICKET_PREFIX}{secrets.token_hex(6)}"


@dataclass(frozen=True, slots=True)
class ConfirmationTicket:
    """One operation waiting for an answer, and everything needed to run it.

    Attributes:
        ticket_id: What the user quotes to answer. Unguessable, but never a
            credential on its own.
        subject: The authenticated caller this confirmation belongs to.
        conversation_id: The conversation it was raised in.
        tool_name: Capability to re-invoke once approved.
        request: What the person reads, and what the domain gate then enforces.
            Keeping one object for both is what makes the audit trail record the
            operation that was actually described.
        arguments: The exact arguments to replay. Stored so the execution cannot
            drift from the description.
        expires_at: When the ticket stops being claimable.
    """

    ticket_id: str
    subject: str
    conversation_id: str
    tool_name: str
    request: ConfirmationRequest
    arguments: Mapping[str, Any]
    expires_at: datetime

    @classmethod
    def issue(
        cls,
        *,
        subject: str,
        conversation_id: str,
        tool_name: str,
        request: ConfirmationRequest,
        arguments: Mapping[str, Any],
        now: datetime | None = None,
        lifetime: timedelta = DEFAULT_TICKET_LIFETIME,
    ) -> ConfirmationTicket:
        """Create a ticket for an operation that has *not* been performed."""
        issued_at = now or datetime.now(UTC)
        return cls(
            ticket_id=new_ticket_id(),
            subject=subject,
            conversation_id=conversation_id,
            tool_name=tool_name,
            request=request,
            arguments=dict(arguments),
            expires_at=issued_at + lifetime,
        )

    def has_expired(self, now: datetime) -> bool:
        """Whether this ticket may no longer be claimed."""
        return now >= self.expires_at

    def belongs_to(self, subject: str, conversation_id: str) -> bool:
        """Whether this ticket was raised for the given caller and conversation."""
        return self.subject == subject and self.conversation_id == conversation_id


@runtime_checkable
class PendingConfirmationStore(Protocol):
    """Holds the confirmations a caller has been asked about."""

    def issue(self, ticket: ConfirmationTicket) -> None:
        """Record a ticket as awaiting an answer."""
        ...

    def claim(self, ticket_id: str, *, subject: str, conversation_id: str) -> ConfirmationTicket:
        """Consume a ticket, or refuse it.

        Raises:
            UnknownTicketError: no claimable ticket matches, whether because it
                never existed, was already claimed, expired, or belongs to
                another caller or conversation.
        """
        ...

    def pending(self, *, subject: str, conversation_id: str) -> tuple[ConfirmationTicket, ...]:
        """Return the unanswered tickets of one conversation, oldest first."""
        ...

    def discard(self, *, subject: str, conversation_id: str) -> None:
        """Drop every ticket of a conversation, answered or not."""
        ...


@dataclass(slots=True)
class InMemoryPendingConfirmationStore:
    """Ticket store for one process, which is the whole lifetime of the PoC.

    A durable store is a drop-in replacement: everything that makes a claim safe
    is decided here, not by the caller.
    """

    clock: Clock = _utc_now
    _tickets: dict[str, ConfirmationTicket] = field(default_factory=dict, init=False)

    def issue(self, ticket: ConfirmationTicket) -> None:
        """Record a ticket as awaiting an answer."""
        self._tickets[ticket.ticket_id] = ticket

    def claim(self, ticket_id: str, *, subject: str, conversation_id: str) -> ConfirmationTicket:
        """Consume a ticket, refusing anything that does not match exactly."""
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            raise UnknownTicketError(ticket_id)
        if not ticket.belongs_to(subject, conversation_id):
            # Deliberately the same error as an absent ticket: telling a caller
            # that somebody else's confirmation exists is itself a disclosure.
            raise UnknownTicketError(ticket_id)
        if ticket.has_expired(self._now()):
            del self._tickets[ticket_id]
            raise UnknownTicketError(ticket_id)

        del self._tickets[ticket_id]
        return ticket

    def pending(self, *, subject: str, conversation_id: str) -> tuple[ConfirmationTicket, ...]:
        """Return the unanswered tickets of one conversation, oldest first."""
        now = self._now()
        return tuple(
            ticket
            for ticket in self._tickets.values()
            if ticket.belongs_to(subject, conversation_id) and not ticket.has_expired(now)
        )

    def discard(self, *, subject: str, conversation_id: str) -> None:
        """Drop every ticket of a conversation, answered or not."""
        for ticket_id in [
            ticket_id for ticket_id, ticket in self._tickets.items() if ticket.belongs_to(subject, conversation_id)
        ]:
            del self._tickets[ticket_id]

    def _now(self) -> datetime:
        """Current time, injectable so expiry is testable without waiting."""
        return self.clock()
