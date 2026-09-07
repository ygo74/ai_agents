"""Ports the mail domain needs from the surrounding application."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.models import EmailAddress, MailDraft


@runtime_checkable
class MailboxOwnerDirectory(Protocol):
    """Resolves the mailbox address a user context acts for.

    Composing a reply needs to know which address belongs to the owner, so that
    the owner is not put in their own recipient list. That mapping is deployment
    configuration, not domain knowledge, hence this port.
    """

    def address_of(self, user: UserContext) -> EmailAddress:
        """Return the mailbox address of the given user.

        Raises:
            MailboxOwnerUnknownError: no address is configured for this user.
        """
        ...


@runtime_checkable
class DraftStore(Protocol):
    """Holds the drafts prepared during a conversation.

    Drafting and sending are two separate turns. Keeping the prepared draft on
    the application side, and exchanging only an opaque reference, means the
    content that gets delivered is exactly the content the user approved: a
    model cannot quietly rewrite recipients or body between the two steps.

    Every operation is scoped to a user, so a reference issued for one mailbox
    can never be redeemed against another.
    """

    def put(self, draft: MailDraft, user: UserContext) -> str:
        """Store a draft and return the reference identifying it."""
        ...

    def get(self, reference: str, user: UserContext) -> MailDraft:
        """Return a previously stored draft.

        Raises:
            DraftNotFoundError: unknown reference for this user.
        """
        ...
