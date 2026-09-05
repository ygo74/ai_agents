"""Tests of the mail domain models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from tests.conftest import make_message, make_thread

from ai_agent_lab.domain.mail.models import (
    EmailAddress,
    MailSearchRequest,
    MailSearchResult,
    MailThread,
)
from ai_agent_lab.domain.security.untrusted import UntrustedOrigin, untrusted


class TestEmailAddress:
    """Normalisation and validation of mailbox addresses."""

    def test_normalises_case_and_whitespace(self):
        assert EmailAddress(value="  John.Doe@Example.COM ").value == "john.doe@example.com"

    def test_exposes_the_domain_part(self):
        assert EmailAddress(value="john@example.com").domain == "example.com"

    @pytest.mark.parametrize("value", ["", "john", "john@", "@example.com", "john@example", "a b@example.com"])
    def test_rejects_invalid_addresses(self, value):
        with pytest.raises(ValidationError):
            EmailAddress(value=value)


class TestMailMessage:
    """Projection and invariants of a message."""

    def test_rejects_naive_datetimes(self):
        with pytest.raises(ValidationError):
            make_message(sent_at=datetime(2026, 9, 1, 10, 0))

    def test_normalises_datetimes_to_utc(self):
        message = make_message(sent_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC))

        assert message.sent_at.tzinfo is UTC

    def test_to_header_counts_every_recipient(self):
        message = make_message(to=("a@example.com", "b@example.com"))

        header = message.to_header()

        assert header.recipient_count == 2
        assert header.message_id == message.message_id
        assert header.subject == message.subject

    def test_has_attachments_is_false_without_attachments(self):
        assert not make_message().has_attachments


class TestMailThread:
    """Invariants and derived data of a conversation."""

    def test_rejects_messages_from_another_thread(self):
        foreign = make_message(message_id="m2", thread_id="other")

        with pytest.raises(ValidationError):
            MailThread(
                thread_id="t1",
                subject=untrusted("s", UntrustedOrigin.MAIL_SUBJECT),
                messages=(make_message(), foreign),
            )

    def test_rejects_an_empty_thread(self):
        with pytest.raises(ValidationError):
            MailThread(thread_id="t1", subject=untrusted("s", UntrustedOrigin.MAIL_SUBJECT), messages=())

    def test_participants_are_distinct_and_ordered(self):
        first = make_message(message_id="m1", sender="john@example.com")
        second = make_message(message_id="m2", sender="owner@example.com", to=("john@example.com",))

        thread = make_thread(first, second)

        assert [str(p.address) for p in thread.participants] == ["john@example.com", "owner@example.com"]

    def test_latest_message_and_chronological_order(self):
        older = make_message(message_id="m1", sent_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC))
        newer = make_message(message_id="m2", sent_at=datetime(2026, 9, 2, 8, 0, tzinfo=UTC))

        thread = make_thread(newer, older)

        assert thread.latest_message.message_id == "m2"
        assert [m.message_id for m in thread.in_chronological_order()] == ["m1", "m2"]


class TestMailSearchRequest:
    """Validation of a mailbox query."""

    def test_detects_an_empty_request(self):
        assert MailSearchRequest().is_empty
        assert not MailSearchRequest(unread_only=True).is_empty
        assert not MailSearchRequest(keywords="invoice").is_empty

    def test_rejects_an_inverted_date_range(self):
        with pytest.raises(ValidationError):
            MailSearchRequest(
                date_from=datetime(2026, 9, 5, tzinfo=UTC),
                date_to=datetime(2026, 9, 1, tzinfo=UTC),
            )

    @pytest.mark.parametrize("limit", [0, -1, 1000])
    def test_rejects_out_of_range_limits(self, limit):
        with pytest.raises(ValidationError):
            MailSearchRequest(limit=limit)


class TestMailSearchResult:
    """Consistency of a search outcome."""

    def test_rejects_a_total_smaller_than_the_returned_headers(self):
        with pytest.raises(ValidationError):
            MailSearchResult(headers=(make_message().to_header(),), total_count=0)

    def test_accepts_a_truncated_result(self):
        result = MailSearchResult(headers=(make_message().to_header(),), total_count=42, truncated=True)

        assert result.truncated
        assert result.total_count == 42
