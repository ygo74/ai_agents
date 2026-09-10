"""What a chat user reads when operations are waiting for their answer.

A console asks about one operation and holds the turn, so the question is still
on screen when the person answers. A chat surface has no such luxury: the reply
is sent, the conversation moves on, and the answer may come several messages
later - by which time a bare list of identifiers means nothing without scrolling
back to find out which message each one was.

So each ticket is rendered with the facts the presenter already resolved for it -
the subject, the sender, the label's name rather than its identifier - next to
the words that answer it. Those facts are written by the application, from the
very request that will authorise the operation, so what the reader judges is what
gets executed and audited. A model paraphrasing the list could drop an entry or
describe one it is not about.

The values come from mail, which is third-party data, so they are contained: one
line each, and long ones are cut. A subject cannot become a new entry in the
list, and cannot flood the reply.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ai_agent_lab.core.security.confirmation import ConfirmationDetail
from ai_agent_lab.core.security.tickets import TICKET_PREFIX, ConfirmationTicket

_HEADING = "Awaiting your confirmation - nothing has been changed yet:"

# Long enough for a mail subject, short enough that a crafted one cannot bury
# the rest of the reply.
_MAX_VALUE = 160
_ELLIPSIS = "..."

# A ticket reference is the one token the approval grammar turns on, so a mail
# subject is not allowed to display one. Quoting an invented reference authorises
# nothing - identifiers are unguessable and an unknown one is refused - but it
# lets third-party content imitate the application asking for an approval, and
# that is a conversation nobody should have to second-guess.
_REFERENCE = re.compile(rf"{re.escape(TICKET_PREFIX)}[0-9a-f]*", re.IGNORECASE)
_REDACTED = "[reference removed]"


class PendingConfirmationRenderer:
    """Renders the tickets of a conversation as text a person can act on."""

    def render(self, tickets: Sequence[ConfirmationTicket]) -> str:
        """Return the block appended to a reply, or nothing when none is waiting."""
        if not tickets:
            return ""

        lines = ["", "", _HEADING]
        for ticket in tickets:
            lines.extend(self._entry(ticket))
        return "\n".join(lines)

    def _entry(self, ticket: ConfirmationTicket) -> list[str]:
        """Render one ticket: what it would do, to what, and how to answer."""
        lines = ["", f"- **{ticket.request.title}**"]
        lines.extend(f"  - {self._detail(detail)}" for detail in ticket.request.details)
        lines.append(f"  - Reply `CONFIRM {ticket.ticket_id}` to approve, `CANCEL {ticket.ticket_id}` to decline.")
        return lines

    @staticmethod
    def _detail(detail: ConfirmationDetail) -> str:
        """Render one labelled fact, on exactly one line."""
        return f"{detail.label}: {_contained(detail.value)}"


def _contained(value: str) -> str:
    """Reduce untrusted text to a single bounded line, quoting no reference."""
    flattened = _REFERENCE.sub(_REDACTED, " ".join(value.split()))
    if len(flattened) <= _MAX_VALUE:
        return flattened
    return flattened[: _MAX_VALUE - len(_ELLIPSIS)] + _ELLIPSIS
