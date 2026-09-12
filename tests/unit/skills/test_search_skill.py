"""Tests of the search and retrieval skills."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ygo74.agent_runtime.domains.security.security_errors import PermissionDeniedError

from ai_agent_lab.mail.domain.models import EmailAddress, MailSearchRequest
from ai_agent_lab.mail.mail_errors import MailNotFoundError
from ai_agent_lab.mail.skills.search_skill import MailReadSkill, MailSearchSkill


@pytest.fixture
def search_skill(mail_tools):
    """The skill under test."""
    return MailSearchSkill(mail_tools)


@pytest.fixture
def read_skill(mail_tools):
    """The retrieval skill under test."""
    return MailReadSkill(mail_tools)


class TestMailSearchSkill:
    """Structured mailbox search."""

    async def test_searches_by_sender(self, search_skill, owner):
        result = await search_skill.search(MailSearchRequest(sender=EmailAddress(value="john@example.com")), owner)

        assert [header.message_id for header in result.headers] == ["m1"]

    async def test_searches_by_keyword_across_subject_and_body(self, search_skill, owner):
        result = await search_skill.search(MailSearchRequest(keywords="architecture"), owner)

        assert {header.message_id for header in result.headers} == {"m1", "m2"}

    async def test_combines_criteria(self, search_skill, owner):
        result = await search_skill.search(
            MailSearchRequest(subject_contains="Project Alpha", date_from=datetime(2026, 9, 2, tzinfo=UTC)),
            owner,
        )

        assert [header.message_id for header in result.headers] == ["m2"]

    async def test_search_unread_is_a_shortcut_over_the_generic_request(self, search_skill, owner):
        result = await search_skill.search_unread(owner)

        assert {header.message_id for header in result.headers} == {"m1", "m3"}

    async def test_returns_previews_rather_than_bodies(self, search_skill, owner):
        result = await search_skill.search(MailSearchRequest(keywords="architecture"), owner)

        assert all(not hasattr(header, "body") for header in result.headers)

    @pytest.mark.security
    async def test_requires_the_read_permission(self, search_skill):
        from ygo74.agent_runtime.domains.security.user_context import UserContext

        anonymous = UserContext(user_id="owner", session_id="s", permissions=frozenset())

        with pytest.raises(PermissionDeniedError):
            await search_skill.search(MailSearchRequest(keywords="a"), anonymous)


class TestMailReadSkill:
    """Retrieval of a message or a conversation."""

    async def test_reads_one_message_with_its_body(self, read_skill, owner):
        message = await read_skill.read_message("m1", owner)

        assert "architecture document" in message.body.expose()

    async def test_reads_a_thread_in_chronological_order(self, read_skill, owner):
        thread = await read_skill.read_thread("t1", owner)

        assert [message.message_id for message in thread.messages] == ["m1", "m2"]

    async def test_reads_several_messages_in_the_requested_order(self, read_skill, owner):
        messages = await read_skill.read_messages(("m2", "m1"), owner)

        assert [message.message_id for message in messages] == ["m2", "m1"]

    async def test_propagates_a_missing_message_as_a_domain_error(self, read_skill, owner):
        with pytest.raises(MailNotFoundError):
            await read_skill.read_message("absent", owner)

    @pytest.mark.security
    async def test_requires_the_read_permission(self, read_skill, reader):
        from ygo74.agent_runtime.domains.security.user_context import UserContext

        anonymous = UserContext(user_id="owner", session_id="s", permissions=frozenset())

        with pytest.raises(PermissionDeniedError):
            await read_skill.read_thread("t1", anonymous)
