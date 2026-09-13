"""Contracts of the mail MCP tool surface.

This module declares what a mail MCP server offers, using only domain types.
It contains no implementation and no protocol knowledge: whether the server is
backed by Gmail, Microsoft Graph, EWS, IMAP or a fixture is invisible here, and
must stay invisible to every caller.

The surface is split into focused protocols so that a skill depends only on the
capabilities it actually uses. :class:`MailTools` composes them for
implementations and for the composition root.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.domain.models import (
    MailDraft,
    MailLabel,
    MailLabelOutcome,
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailSendRequest,
    MailSendResult,
    MailThread,
)


@runtime_checkable
class MailReadTools(Protocol):
    """Read-only access to a mailbox."""

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query.

        Headers rather than full messages are returned so that a broad query
        does not pull entire bodies into the conversation.
        """
        ...

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message.

        Raises:
            MailNotFoundError: no such message for this user.
            MailAccessDeniedError: the mail system refused the access.
        """
        ...

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation.

        Raises:
            MailNotFoundError: no such thread for this user.
            MailAccessDeniedError: the mail system refused the access.
        """
        ...

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels and folders available in the mailbox."""
        ...


@runtime_checkable
class MailDraftTools(Protocol):
    """Preparation of messages that are not sent."""

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft and return it with its assigned identifier.

        This writes to the mailbox but delivers nothing.
        """
        ...


@runtime_checkable
class MailSendTools(Protocol):
    """Delivery of a prepared message."""

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Deliver a draft to its recipients.

        This is irreversible. Callers must have obtained an explicit user
        confirmation before invoking it.
        """
        ...


@runtime_checkable
class MailOrganisationTools(Protocol):
    """Mailbox housekeeping operations on a message."""

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread."""
        ...

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        ...

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label or category to a message."""
        ...

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label or category from a message."""
        ...


@runtime_checkable
class MailLabelTools(Protocol):
    """Changes to which labels a mailbox has.

    Separate from :class:`MailOrganisationTools` because these act on the shape
    of the mailbox rather than on a message in it. A skill that files messages
    needs one; a skill that curates the label set needs the other.
    """

    async def create_label(self, name: str, user: UserContext) -> MailLabelOutcome:
        """Make a label exist, reporting whether it had to be created.

        Asking for a label that already exists is not an error: it is what a
        caller organising a mailbox does most of the time.
        """
        ...

    async def delete_label(self, label_id: str, user: UserContext) -> None:
        """Delete a label, detaching it from every message carrying it.

        This is irreversible. Callers must have obtained an explicit user
        confirmation before invoking it.

        Raises:
            MailNotFoundError: no such label for this user.
            MailAccessDeniedError: the label belongs to the mail system itself.
        """
        ...


@runtime_checkable
class MailTools(
    MailReadTools,
    MailDraftTools,
    MailSendTools,
    MailOrganisationTools,
    MailLabelTools,
    Protocol,
):
    """The complete mail MCP surface."""
