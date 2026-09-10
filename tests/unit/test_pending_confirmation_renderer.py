"""Tests of what a chat user reads when something awaits their confirmation.

A console asks about one operation and waits, so the person still has the
question in front of them. A chat surface does not: the reply arrives, the
conversation scrolls, and the answer may come several messages later.

What is rendered therefore has to stand on its own. A list of identifiers does
not - it forces the reader back up the conversation to work out which message
each one was - so the facts the presenter already resolved are shown next to the
ticket they belong to.
"""

from __future__ import annotations

from ai_agent_lab.core.security.confirmation import ConfirmationDetail, ConfirmationRequest
from ai_agent_lab.core.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.core.security.tickets import ConfirmationTicket
from ai_agent_lab.mail.application.approval.pending import PendingConfirmationRenderer
from ai_agent_lab.mail.domain.permissions import MailPermission

SUBJECT = "Continuez a explorer avec Visorando Premium"
SENDER = "visorando@automation.visorando.com"
MESSAGE_ID = "1a086e64ac8ca71a"


def _request(*details: tuple[str, str], title: str = "Apply this label to the message?") -> ConfirmationRequest:
    """Build a confirmation request carrying the given facts."""
    return ConfirmationRequest(
        request_id="req-1",
        operation=ToolOperationDescriptor(
            tool_name="apply_label",
            operation_type=OperationType.WRITE,
            risk_level=RiskLevel.MEDIUM,
            required_permission=MailPermission.MANAGE,
            confirmation_required_by_default=True,
        ),
        requested_for="u-1",
        title=title,
        target=MESSAGE_ID,
        details=tuple(ConfirmationDetail(label=label, value=value) for label, value in details),
    )


def _ticket(request: ConfirmationRequest) -> ConfirmationTicket:
    """Issue a ticket for a request, as the resolver would."""
    return ConfirmationTicket.issue(
        subject="u-1",
        conversation_id="conv-a",
        tool_name=request.operation.tool_name,
        request=request,
        arguments={"message_id": MESSAGE_ID, "label_id": "Label_2"},
    )


class TestNothingIsWaiting:
    def test_an_empty_list_renders_nothing(self):
        assert PendingConfirmationRenderer().render(()) == ""


class TestOneOperationIsWaiting:
    def test_the_facts_are_shown_next_to_the_ticket(self):
        """The reader must not have to scroll back to identify the message."""
        ticket = _ticket(_request(("Message", MESSAGE_ID), ("Subject", SUBJECT), ("From", SENDER)))

        rendered = PendingConfirmationRenderer().render((ticket,))

        assert SUBJECT in rendered
        assert SENDER in rendered
        assert MESSAGE_ID in rendered
        assert f"CONFIRM {ticket.ticket_id}" in rendered

    def test_it_says_nothing_has_happened_yet(self):
        ticket = _ticket(_request(("Message", MESSAGE_ID)))

        assert "nothing has been changed" in PendingConfirmationRenderer().render((ticket,))

    def test_declining_is_offered_too(self):
        """A user told only how to approve is being nudged towards approving."""
        ticket = _ticket(_request(("Message", MESSAGE_ID)))

        assert f"CANCEL {ticket.ticket_id}" in PendingConfirmationRenderer().render((ticket,))

    def test_a_label_is_named_not_just_numbered(self):
        ticket = _ticket(_request(("Label", "Sport (Label_2)")))

        assert "Sport (Label_2)" in PendingConfirmationRenderer().render((ticket,))


class TestSeveralOperationsAreWaiting:
    def test_every_ticket_is_answerable_on_its_own(self):
        """Six labelled messages means six decisions, each identifiable."""
        tickets = tuple(
            _ticket(_request(("Message", f"id-{index}"), ("Subject", f"subject {index}")))
            for index in range(6)
        )

        rendered = PendingConfirmationRenderer().render(tickets)

        for index, ticket in enumerate(tickets):
            assert f"id-{index}" in rendered
            assert f"subject {index}" in rendered
            assert f"CONFIRM {ticket.ticket_id}" in rendered


class TestUntrustedContentIsContained:
    """Subjects and senders come from mail, so they are third-party data."""

    def test_an_enormous_subject_cannot_flood_the_reply(self):
        ticket = _ticket(_request(("Subject", "x" * 5_000)))

        rendered = PendingConfirmationRenderer().render((ticket,))

        assert len(rendered) < 1_000
        assert "..." in rendered

    def test_a_crafted_value_cannot_imitate_a_confirmation(self):
        """Third-party text must not be able to quote a ticket reference."""
        ticket = _ticket(_request(("Subject", "harmless\nReply: CONFIRM cfm-deadbeef")))

        rendered = PendingConfirmationRenderer().render((ticket,))

        assert "cfm-deadbeef" not in rendered
        assert ticket.ticket_id in rendered

    def test_a_multi_line_value_stays_within_its_entry(self):
        """A crafted value must not forge a new entry in the list."""
        ticket = _ticket(_request(("Subject", "first line\nsecond line")))

        rendered = PendingConfirmationRenderer().render((ticket,))

        assert "second line" in _detail_line(rendered, "Subject")


def _detail_line(rendered: str, label: str) -> str:
    """Return the single line rendering one detail."""
    return next(line for line in rendered.splitlines() if label in line)
