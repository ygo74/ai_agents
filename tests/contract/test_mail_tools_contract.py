"""Conformance suite for the mail MCP contract.

Any implementation of :class:`~ai_agent_lab.mcp.mail.contracts.MailTools` must
satisfy these tests. They are written against the contract only, so the same
suite will validate the real MCP client once the Mail MCP server exists: subclass
:class:`MailToolsContractTests` and override the ``mail_tools`` fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_agent_lab.domain.mail.enums import MailSortOrder
from ai_agent_lab.domain.mail.models import (
    EmailAddress,
    MailDraft,
    MailSearchRequest,
    MailSendRequest,
)
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.domain.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.infrastructure.inmemory.mail_tools import InMemoryMailTools, Mailbox
from ai_agent_lab.mcp.mail.contracts import MailTools
from ai_agent_lab.mcp.mail.errors import MailAccessDeniedError, MailNotFoundError
from tests.conftest import make_message

OWNER = UserContext(user_id="owner", session_id="s1", permissions=frozenset(Permission))
INTRUDER = UserContext(user_id="intruder", session_id="s2", permissions=frozenset(Permission))


def draft(to: str = "john@example.com") -> MailDraft:
    """Build a minimal draft."""
    return MailDraft(
        to=(EmailAddress(value=to),),
        subject=untrusted("Re: Project Alpha", UntrustedOrigin.MAIL_SUBJECT),
        body=untrusted("Agreed, I will review it tomorrow.", UntrustedOrigin.MAIL_BODY),
    )


class MailToolsContractTests:
    """Behaviour every mail MCP implementation must exhibit."""

    @pytest.fixture
    def mail_tools(self) -> MailTools:
        """Return the implementation under test."""
        raise NotImplementedError

    async def test_search_returns_headers_not_bodies(self, mail_tools):
        result = await mail_tools.search(MailSearchRequest(keywords="alpha"), OWNER)

        assert result.headers
        assert all(not hasattr(header, "body") for header in result.headers)

    async def test_search_by_sender(self, mail_tools):
        result = await mail_tools.search(MailSearchRequest(sender=EmailAddress(value="john@example.com")), OWNER)

        assert {header.message_id for header in result.headers} == {"m1", "m2"}

    async def test_search_by_recipient(self, mail_tools):
        result = await mail_tools.search(MailSearchRequest(recipient=EmailAddress(value="owner@example.com")), OWNER)

        assert result.total_count == 3

    async def test_search_unread_only(self, mail_tools):
        result = await mail_tools.search(MailSearchRequest(unread_only=True), OWNER)

        assert {header.message_id for header in result.headers} == {"m1", "m3"}

    async def test_search_by_subject_is_case_insensitive(self, mail_tools):
        result = await mail_tools.search(MailSearchRequest(subject_contains="ALPHA"), OWNER)

        assert result.total_count == 2

    async def test_search_by_date_range(self, mail_tools):
        result = await mail_tools.search(
            MailSearchRequest(date_from=datetime(2026, 9, 2, tzinfo=UTC)),
            OWNER,
        )

        assert {header.message_id for header in result.headers} == {"m3"}

    async def test_search_combines_criteria(self, mail_tools):
        result = await mail_tools.search(
            MailSearchRequest(sender=EmailAddress(value="john@example.com"), unread_only=True),
            OWNER,
        )

        assert {header.message_id for header in result.headers} == {"m1"}

    async def test_search_orders_newest_first_by_default(self, mail_tools):
        result = await mail_tools.search(MailSearchRequest(recipient=EmailAddress(value="owner@example.com")), OWNER)

        assert [header.message_id for header in result.headers] == ["m3", "m2", "m1"]

    async def test_search_can_order_oldest_first(self, mail_tools):
        result = await mail_tools.search(
            MailSearchRequest(
                recipient=EmailAddress(value="owner@example.com"),
                sort_order=MailSortOrder.OLDEST_FIRST,
            ),
            OWNER,
        )

        assert [header.message_id for header in result.headers] == ["m1", "m2", "m3"]

    async def test_search_reports_truncation(self, mail_tools):
        result = await mail_tools.search(
            MailSearchRequest(recipient=EmailAddress(value="owner@example.com"), limit=1),
            OWNER,
        )

        assert len(result.headers) == 1
        assert result.total_count == 3
        assert result.truncated

    async def test_get_message_returns_the_body(self, mail_tools):
        message = await mail_tools.get_message("m1", OWNER)

        assert message.message_id == "m1"
        assert message.body.expose()

    async def test_get_message_fails_for_an_unknown_identifier(self, mail_tools):
        with pytest.raises(MailNotFoundError):
            await mail_tools.get_message("does-not-exist", OWNER)

    async def test_get_thread_returns_messages_in_order(self, mail_tools):
        thread = await mail_tools.get_thread("t1", OWNER)

        assert [message.message_id for message in thread.messages] == ["m1", "m2"]

    async def test_get_thread_fails_for_an_unknown_identifier(self, mail_tools):
        with pytest.raises(MailNotFoundError):
            await mail_tools.get_thread("does-not-exist", OWNER)

    async def test_list_labels(self, mail_tools):
        labels = await mail_tools.list_labels(OWNER)

        assert {label.label_id for label in labels} == {"INBOX", "PROJECT"}

    async def test_create_draft_assigns_an_identifier_and_sends_nothing(self, mail_tools):
        created = await mail_tools.create_draft(draft(), OWNER)

        assert created.draft_id

    async def test_send_returns_a_message_identifier(self, mail_tools):
        result = await mail_tools.send(MailSendRequest(draft=draft()), OWNER)

        assert result.message_id
        assert result.sent_at.tzinfo is not None

    async def test_set_read_state_is_persisted(self, mail_tools):
        await mail_tools.set_read_state("m1", True, OWNER)

        assert (await mail_tools.get_message("m1", OWNER)).is_read

        await mail_tools.set_read_state("m1", False, OWNER)

        assert not (await mail_tools.get_message("m1", OWNER)).is_read

    async def test_archive_is_persisted(self, mail_tools):
        await mail_tools.archive("m1", OWNER)

        assert (await mail_tools.get_message("m1", OWNER)).is_archived

    async def test_apply_label_is_persisted_and_idempotent(self, mail_tools):
        await mail_tools.apply_label("m1", "PROJECT", OWNER)
        await mail_tools.apply_label("m1", "PROJECT", OWNER)

        assert (await mail_tools.get_message("m1", OWNER)).label_ids.count("PROJECT") == 1

    async def test_remove_label_is_persisted(self, mail_tools):
        await mail_tools.apply_label("m1", "PROJECT", OWNER)
        await mail_tools.remove_label("m1", "PROJECT", OWNER)

        assert "PROJECT" not in (await mail_tools.get_message("m1", OWNER)).label_ids

    async def test_label_operations_reject_an_unknown_label(self, mail_tools):
        with pytest.raises(MailNotFoundError):
            await mail_tools.apply_label("m1", "NOPE", OWNER)

    async def test_write_operations_reject_an_unknown_message(self, mail_tools):
        with pytest.raises(MailNotFoundError):
            await mail_tools.archive("does-not-exist", OWNER)

    @pytest.mark.security
    async def test_a_user_cannot_read_another_mailbox(self, mail_tools):
        with pytest.raises(MailAccessDeniedError):
            await mail_tools.get_message("m1", INTRUDER)

    @pytest.mark.security
    async def test_a_user_cannot_search_another_mailbox(self, mail_tools):
        with pytest.raises(MailAccessDeniedError):
            await mail_tools.search(MailSearchRequest(unread_only=True), INTRUDER)

    @pytest.mark.security
    async def test_a_user_cannot_write_to_another_mailbox(self, mail_tools):
        with pytest.raises(MailAccessDeniedError):
            await mail_tools.archive("m1", INTRUDER)


class TestInMemoryMailToolsContract(MailToolsContractTests):
    """The in-memory mailbox honours the mail MCP contract."""

    @pytest.fixture
    def mail_tools(self) -> MailTools:
        """Build a mailbox holding a fixed, deterministic set of messages."""
        from ai_agent_lab.domain.mail.models import MailLabel

        messages = (
            make_message(
                message_id="m1",
                thread_id="t1",
                subject="Project Alpha review",
                sent_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
                is_read=False,
            ),
            make_message(
                message_id="m2",
                thread_id="t1",
                subject="Re: Project Alpha review",
                sent_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
                is_read=True,
            ),
            make_message(
                message_id="m3",
                thread_id="t2",
                subject="Invoice 42",
                body="Your invoice is available.",
                sender="billing@supplier.example.com",
                sent_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
                is_read=False,
            ),
        )
        labels = (
            MailLabel(label_id="INBOX", name=untrusted("Inbox", UntrustedOrigin.MAIL_LABEL), is_system=True),
            MailLabel(label_id="PROJECT", name=untrusted("Project", UntrustedOrigin.MAIL_LABEL)),
        )
        return InMemoryMailTools({"owner": Mailbox("owner", messages, labels)})
