"""Port for the mailbox address associated with a user."""

from typing import Protocol, runtime_checkable

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.domain.models import EmailAddress


@runtime_checkable
class MailboxOwnerDirectory(Protocol):
    """Resolve an owner without exposing deployment configuration to skills."""

    def address_of(self, user: UserContext) -> EmailAddress:
        """Return the owner's address or raise MailboxOwnerUnknownError."""
        ...
