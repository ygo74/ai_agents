"""Tests of confirmations that outlive a turn.

An HTTP API cannot block waiting for a person, so a pending approval leaves the
turn as a ticket and comes back in a later request. That makes the ticket the
security boundary, and these tests pin what it must refuse.

The properties are deliberately checked at *claim* time rather than at issue
time: a ticket is handed out freely, and everything that matters is verified when
somebody tries to use it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_agent_lab.core.security.commands import ConfirmationCommandParser, ConfirmationVerb
from ai_agent_lab.core.security.confirmation import ConfirmationRequest
from ai_agent_lab.core.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.core.security.tickets import (
    ConfirmationTicket,
    InMemoryPendingConfirmationStore,
    UnknownTicketError,
)
from ai_agent_lab.mail.domain.permissions import MailPermission

ADA = "ada-3f9a"
BOB = "bob-77c1"
CONVERSATION = "conv-1"
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

APPLY_LABEL = ToolOperationDescriptor(
    tool_name="apply_label",
    operation_type=OperationType.WRITE,
    risk_level=RiskLevel.MEDIUM,
    required_permission=MailPermission.MANAGE,
    confirmation_required_by_default=True,
)


def request_for(subject: str) -> ConfirmationRequest:
    """Build the request a person would read."""
    return ConfirmationRequest(
        request_id="req-1",
        operation=APPLY_LABEL,
        requested_for=subject,
        title="Apply this label to the message?",
        target="m-alpha-1:Label_5",
    )


def ticket_for(
    subject: str = ADA,
    conversation_id: str = CONVERSATION,
    *,
    arguments: dict[str, object] | None = None,
    lifetime: timedelta = timedelta(minutes=15),
) -> ConfirmationTicket:
    """Issue a ticket for an operation that has not been performed."""
    return ConfirmationTicket.issue(
        subject=subject,
        conversation_id=conversation_id,
        tool_name="apply_label",
        request=request_for(subject),
        arguments=arguments or {"message_id": "m-alpha-1", "label_id": "Label_5"},
        now=NOW,
        lifetime=lifetime,
    )


def store_at(moment: datetime) -> InMemoryPendingConfirmationStore:
    """A store whose clock is frozen, so expiry is testable without waiting."""
    return InMemoryPendingConfirmationStore(clock=lambda: moment)


class TestATicketCarriesWhatWillRun:
    """The description and the execution must not be able to drift apart."""

    def test_it_stores_the_exact_arguments_to_replay(self):
        ticket = ticket_for(arguments={"message_id": "m-1", "label_id": "L-9"})

        assert ticket.arguments == {"message_id": "m-1", "label_id": "L-9"}

    def test_it_carries_the_request_the_person_reads(self):
        ticket = ticket_for()

        assert ticket.request.title == "Apply this label to the message?"
        assert ticket.request.operation.tool_name == "apply_label"

    def test_two_tickets_never_share_an_identifier(self):
        assert ticket_for().ticket_id != ticket_for().ticket_id

    def test_an_identifier_is_not_guessable(self):
        """It is not a credential, but it must not be enumerable either."""
        ticket = ticket_for()

        assert ticket.ticket_id.startswith("cfm-")
        assert len(ticket.ticket_id) > len("cfm-") + 8


@pytest.mark.security
class TestATicketIsClaimedOnce:
    """One approval must never authorise two executions."""

    def test_claiming_returns_the_ticket(self):
        store = store_at(NOW)
        ticket = ticket_for()
        store.issue(ticket)

        claimed = store.claim(ticket.ticket_id, subject=ADA, conversation_id=CONVERSATION)

        assert claimed.arguments == ticket.arguments

    def test_claiming_twice_is_refused(self):
        store = store_at(NOW)
        ticket = ticket_for()
        store.issue(ticket)
        store.claim(ticket.ticket_id, subject=ADA, conversation_id=CONVERSATION)

        with pytest.raises(UnknownTicketError):
            store.claim(ticket.ticket_id, subject=ADA, conversation_id=CONVERSATION)

    def test_an_unknown_identifier_is_refused(self):
        with pytest.raises(UnknownTicketError):
            store_at(NOW).claim("cfm-deadbeef", subject=ADA, conversation_id=CONVERSATION)


@pytest.mark.security
class TestATicketBelongsToOneCaller:
    """A confirmation is personal, and so is the operation it authorises."""

    def test_another_subject_cannot_claim_it(self):
        store = store_at(NOW)
        ticket = ticket_for(subject=ADA)
        store.issue(ticket)

        with pytest.raises(UnknownTicketError):
            store.claim(ticket.ticket_id, subject=BOB, conversation_id=CONVERSATION)

    def test_a_refused_claim_leaves_the_ticket_usable_by_its_owner(self):
        """An intruder must not be able to burn somebody else's confirmation."""
        store = store_at(NOW)
        ticket = ticket_for(subject=ADA)
        store.issue(ticket)

        with pytest.raises(UnknownTicketError):
            store.claim(ticket.ticket_id, subject=BOB, conversation_id=CONVERSATION)

        assert store.claim(ticket.ticket_id, subject=ADA, conversation_id=CONVERSATION).subject == ADA

    def test_another_conversation_cannot_claim_it(self):
        store = store_at(NOW)
        ticket = ticket_for(conversation_id="conv-1")
        store.issue(ticket)

        with pytest.raises(UnknownTicketError):
            store.claim(ticket.ticket_id, subject=ADA, conversation_id="conv-2")

    def test_a_foreign_ticket_is_reported_as_simply_unknown(self):
        """Confirming somebody else's ticket exists is itself a disclosure."""
        store = store_at(NOW)
        ticket = ticket_for(subject=ADA)
        store.issue(ticket)

        with pytest.raises(UnknownTicketError, match="not awaiting an answer"):
            store.claim(ticket.ticket_id, subject=BOB, conversation_id=CONVERSATION)


@pytest.mark.security
class TestATicketExpires:
    """An approval forgotten for an hour is not an approval."""

    def test_an_expired_ticket_is_refused(self):
        ticket = ticket_for(lifetime=timedelta(minutes=15))
        store = store_at(NOW + timedelta(minutes=16))
        store.issue(ticket)

        with pytest.raises(UnknownTicketError):
            store.claim(ticket.ticket_id, subject=ADA, conversation_id=CONVERSATION)

    def test_a_ticket_within_its_lifetime_is_accepted(self):
        ticket = ticket_for(lifetime=timedelta(minutes=15))
        store = store_at(NOW + timedelta(minutes=14))
        store.issue(ticket)

        assert store.claim(ticket.ticket_id, subject=ADA, conversation_id=CONVERSATION) is not None

    def test_an_expired_ticket_is_not_listed_as_pending(self):
        store = store_at(NOW + timedelta(hours=1))
        store.issue(ticket_for())

        assert store.pending(subject=ADA, conversation_id=CONVERSATION) == ()


class TestListingAndDiscarding:
    """A conversation must be able to say what it is waiting for, and forget it."""

    def test_pending_lists_only_the_tickets_of_that_caller(self):
        store = store_at(NOW)
        store.issue(ticket_for(subject=ADA))
        store.issue(ticket_for(subject=BOB))

        assert len(store.pending(subject=ADA, conversation_id=CONVERSATION)) == 1

    def test_discarding_a_conversation_leaves_nothing_claimable(self):
        store = store_at(NOW)
        ticket = ticket_for()
        store.issue(ticket)

        store.discard(subject=ADA, conversation_id=CONVERSATION)

        with pytest.raises(UnknownTicketError):
            store.claim(ticket.ticket_id, subject=ADA, conversation_id=CONVERSATION)

    def test_discarding_one_conversation_spares_another(self):
        store = store_at(NOW)
        kept = ticket_for(conversation_id="conv-2")
        store.issue(ticket_for(conversation_id="conv-1"))
        store.issue(kept)

        store.discard(subject=ADA, conversation_id="conv-1")

        assert store.claim(kept.ticket_id, subject=ADA, conversation_id="conv-2") is not None


class TestReadingAnApproval:
    """The grammar is tiny on purpose: the model must not arbitrate this."""

    @pytest.mark.parametrize(
        "text",
        ["confirm cfm-a1b2c3", "CONFIRM cfm-a1b2c3", "  confirm   cfm-a1b2c3  ", "Confirm cfm-a1b2c3."],
    )
    def test_it_reads_an_approval(self, text):
        command = ConfirmationCommandParser().parse(text)

        assert command is not None
        assert command.verb is ConfirmationVerb.CONFIRM
        assert command.ticket_id == "cfm-a1b2c3"
        assert command.approves

    def test_it_reads_a_refusal(self):
        command = ConfirmationCommandParser().parse("cancel cfm-a1b2c3")

        assert command is not None
        assert not command.approves

    @pytest.mark.security
    @pytest.mark.parametrize(
        "text",
        [
            "please confirm cfm-a1b2c3",
            "confirm cfm-a1b2c3 and archive the rest",
            "what does confirm cfm-a1b2c3 do?",
            "confirm",
            "confirm all",
            "yes",
            "confirm cfm-",
            "confirm xyz-a1b2c3",
        ],
    )
    def test_anything_ambiguous_is_not_an_approval(self, text):
        """A message that merely mentions a ticket must never approve it."""
        assert ConfirmationCommandParser().parse(text) is None
