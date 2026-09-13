"""Permissions declared by the mail domain.

Adding a Jira or Confluence agent declares its own permissions in its own
domain package; nothing here changes.
"""

from __future__ import annotations

from typing import Final

from ygo74.agent_runtime.domains.security.permissions import Permission

_DOMAIN: Final = "mail"


class MailPermission:
    """The capabilities the mail domain gates."""

    READ: Final = Permission(_DOMAIN, "read")
    DRAFT: Final = Permission(_DOMAIN, "draft")
    SEND: Final = Permission(_DOMAIN, "send")
    MANAGE: Final = Permission(_DOMAIN, "manage")

    @classmethod
    def declared(cls) -> frozenset[Permission]:
        """Return every permission the mail domain declares."""
        return frozenset({cls.READ, cls.DRAFT, cls.SEND, cls.MANAGE})
