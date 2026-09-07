"""Shared fixtures and builders for the test suite."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.mail.domain.models import (
    EmailAddress,
    MailMessage,
    MailParticipant,
    MailThread,
)
from ai_agent_lab.mail.domain.permissions import MailPermission

OWNER_EMAIL = "owner@example.com"


def make_participant(address: str, display_name: str | None = None) -> MailParticipant:
    """Build a participant from a raw address."""
    return MailParticipant(
        address=EmailAddress(value=address),
        display_name=None if display_name is None else untrusted(display_name, UntrustedOrigin.MAIL_SENDER_NAME),
    )


def make_message(
    *,
    message_id: str = "m1",
    thread_id: str = "t1",
    subject: str = "Project Alpha",
    body: str = "Please review the architecture document before Friday.",
    sender: str = "john@example.com",
    to: tuple[str, ...] = (OWNER_EMAIL,),
    sent_at: datetime | None = None,
    is_read: bool = False,
    is_archived: bool = False,
    label_ids: tuple[str, ...] = (),
) -> MailMessage:
    """Build a message with sensible defaults."""
    return MailMessage(
        message_id=message_id,
        thread_id=thread_id,
        subject=untrusted(subject, UntrustedOrigin.MAIL_SUBJECT),
        body=untrusted(body, UntrustedOrigin.MAIL_BODY),
        sender=make_participant(sender),
        to=tuple(make_participant(address) for address in to),
        sent_at=sent_at or datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        is_read=is_read,
        is_archived=is_archived,
        label_ids=label_ids,
    )


def make_thread(*messages: MailMessage) -> MailThread:
    """Build a thread from messages sharing a thread identifier."""
    first = messages[0]
    return MailThread(thread_id=first.thread_id, subject=first.subject, messages=messages)


@pytest.fixture(autouse=True)
def deterministic_backend(monkeypatch):
    """Keep the suite independent of the developer's ``.env``.

    Environment variables win over the file, so declaring the backend here makes
    every test run against the deterministic dataset whatever a machine happens
    to be configured for. A test that needs another backend overrides these.

    Real OAuth credentials are removed for the same reason: no test may reach a
    live mail server, even by accident.
    """
    monkeypatch.setenv("MAIL_AGENT_MODE", "mock")
    monkeypatch.setenv("MAIL_MCP_SERVER", "local")
    for name in ("MAIL_MCP_OAUTH_CLIENT_ID", "MAIL_MCP_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def owner() -> UserContext:
    """A mailbox owner holding every mail permission."""
    return UserContext(
        user_id="owner",
        session_id="session-1",
        permissions=MailPermission.declared(),
    )


@pytest.fixture
def reader() -> UserContext:
    """A user allowed to read but not to write."""
    return UserContext(
        user_id="reader",
        session_id="session-2",
        permissions=frozenset({MailPermission.READ}),
    )
