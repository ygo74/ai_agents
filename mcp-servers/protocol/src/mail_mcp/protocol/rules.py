"""Rules every mail server enforces the same way.

Most behaviour belongs to the mail system behind a server. A few rules do not:
they are part of what a caller is promised, and a server that applied them
differently would be a different contract wearing the same tool names.

There is one such rule today, and it exists because the alternative is silent
damage: a system label is not deletable, and each backend refuses that in its
own words, at its own moment, or not at all.
"""

from __future__ import annotations

from mail_mcp.protocol import payloads as wire
from mail_mcp.protocol.errors import AccessDeniedError


def require_deletable(label: wire.Label) -> None:
    """Refuse the deletion of a label the mailbox itself owns.

    Deleting ``INBOX`` or ``UNREAD`` is not a mailbox the caller organises, it
    is the mailbox breaking. The refusal is raised here rather than left to the
    backend so that every server answers it with the same code.
    """
    if not label.is_system:
        return
    raise AccessDeniedError(f"label {label.name!r} is a system label and cannot be deleted")
