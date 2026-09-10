"""Permissions declared by the wiki domain.

Separate from the mail permissions and from any future document permissions: a
person allowed to read a mailbox is not thereby allowed to read a wiki.
"""

from __future__ import annotations

from typing import Final

from ai_agent_lab.core.security.permissions import Permission

_DOMAIN: Final = "wiki"


class WikiPermission:
    """The capabilities the wiki domain gates."""

    READ: Final = Permission(_DOMAIN, "read")
    AUTHOR: Final = Permission(_DOMAIN, "author")
    COMMENT: Final = Permission(_DOMAIN, "comment")
    MANAGE: Final = Permission(_DOMAIN, "manage")

    @classmethod
    def declared(cls) -> frozenset[Permission]:
        """Return every permission the wiki domain declares."""
        return frozenset({cls.READ, cls.AUTHOR, cls.COMMENT, cls.MANAGE})
