"""Resolution of the mailbox a user context acts for."""

from __future__ import annotations

from collections.abc import Mapping

from ai_agent_lab.domain.mail.errors import MailboxOwnerUnknownError
from ai_agent_lab.domain.mail.models import EmailAddress
from ai_agent_lab.domain.security.context import UserContext


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
