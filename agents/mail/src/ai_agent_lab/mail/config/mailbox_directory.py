"""Resolution of the mailbox a user context acts for."""

from __future__ import annotations

from collections.abc import Mapping

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.errors import MailboxOwnerUnknownError
from ai_agent_lab.mail.domain.models import EmailAddress


class ConfiguredMailboxOwnerDirectory:
    """Maps user identifiers to mailbox addresses, from configuration."""

    def __init__(self, addresses_by_user: Mapping[str, str]) -> None:
        self._addresses = {user_id: EmailAddress(value=address) for user_id, address in addresses_by_user.items()}

    def address_of(self, user: UserContext) -> EmailAddress:
        """Return the mailbox address configured for the given user."""
        address = self._addresses.get(user.user_id)
        if address is None:
            raise MailboxOwnerUnknownError(user.user_id)
        return address
