"""Reading an approval out of what the user typed.

This runs **before** the model sees the turn, and that ordering is the whole
point. An approval that reached the model first would be an approval the model
could reinterpret, and the language model must never be the authority on whether
a side effect may happen.

So the grammar is deliberately tiny and literal: a verb and a ticket identifier.
There is no attempt to understand "yes go ahead" or "do the first two". Anything
that is not an exact match is not a confirmation - it is an ordinary message, and
it is handed to the model as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from ai_agent_lab.core.security.tickets import TICKET_PREFIX


class ConfirmationVerb(StrEnum):
    """What the user asked to do with a pending confirmation."""

    CONFIRM = "confirm"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class ConfirmationCommand:
    """An answer to one pending confirmation."""

    verb: ConfirmationVerb
    ticket_id: str

    @property
    def approves(self) -> bool:
        """Whether this command authorises the operation to run."""
        return self.verb is ConfirmationVerb.CONFIRM


_PATTERN = re.compile(
    rf"^\s*(?P<verb>confirm|cancel)\s+(?P<ticket>{re.escape(TICKET_PREFIX)}[0-9a-f]+)\s*[.!]?\s*$",
    re.IGNORECASE,
)


class ConfirmationCommandParser:
    """Recognises an approval, and refuses to guess at anything else."""

    def parse(self, text: str) -> ConfirmationCommand | None:
        """Return the command the text carries, or nothing.

        Returning ``None`` is the normal case: most messages are not answers to
        a confirmation. Only an exact, unambiguous match is treated as one, so a
        message that merely mentions a ticket while asking something else can
        never approve it.
        """
        match = _PATTERN.match(text)
        if match is None:
            return None
        return ConfirmationCommand(
            verb=ConfirmationVerb(match.group("verb").lower()),
            ticket_id=match.group("ticket").lower(),
        )
