"""Errors of the mail domain."""

from __future__ import annotations

from ai_agent_lab.core.errors import DomainError


class MailDomainError(DomainError):
    """Base class for errors of the mail domain."""


class MailboxOwnerUnknownError(MailDomainError):
    """Raised when no mailbox address is configured for a user."""

    def __init__(self, user_id: str) -> None:
        super().__init__(f"no mailbox address is configured for user {user_id!r}")
        self.user_id = user_id


class NoReplyRecipientError(MailDomainError):
    """Raised when a reply would have no recipient at all.

    Sending a message with an empty recipient list is meaningless, and silently
    dropping the reply would hide the problem from the user.
    """

    def __init__(self, message_id: str) -> None:
        super().__init__(f"replying to message {message_id!r} would have no recipient")
        self.message_id = message_id


class DraftNotFoundError(MailDomainError):
    """Raised when a draft reference cannot be redeemed by this user."""

    def __init__(self, reference: str) -> None:
        super().__init__(f"no draft is available under reference {reference!r}")
        self.reference = reference
