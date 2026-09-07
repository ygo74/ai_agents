"""Translation of a mailbox query into Gmail search syntax.

The protocol carries a query as separate criteria; Gmail takes a single string.
Building it is deterministic work - operator names, quoting, date formatting -
so it lives in code and is tested on its own.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

_DATE_FORMAT = "%Y/%m/%d"


class GmailQuery:
    """Renders search criteria as a Gmail query string."""

    def build(
        self,
        *,
        keywords: str | None = None,
        sender: str | None = None,
        recipient: str | None = None,
        subject_contains: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        unread_only: bool = False,
        has_attachments: bool | None = None,
    ) -> str:
        """Return the query Gmail should evaluate.

        Labels are deliberately absent. Gmail's ``label:`` operator matches a
        label by the name a person reads, while a caller holds identifiers, so
        the query string cannot express the filter. It is passed instead as the
        ``labelIds`` request parameter, which is exact.
        """
        terms = (
            *self._envelope(keywords, sender, recipient, subject_contains),
            *self._state(unread_only, has_attachments, date_from, date_to),
        )
        return " ".join(terms).strip()

    def _envelope(
        self,
        keywords: str | None,
        sender: str | None,
        recipient: str | None,
        subject_contains: str | None,
    ) -> Iterator[str]:
        """Yield the terms bearing on who wrote what."""
        if sender:
            yield f"from:{sender}"
        if recipient:
            yield f"to:{recipient}"
        if subject_contains:
            yield f"subject:{self._quoted(subject_contains)}"
        if keywords:
            yield keywords

    def _state(
        self,
        unread_only: bool,
        has_attachments: bool | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Iterator[str]:
        """Yield the terms bearing on state and dates."""
        if unread_only:
            yield "is:unread"
        if has_attachments is True:
            yield "has:attachment"
        if has_attachments is False:
            yield "-has:attachment"
        if date_from is not None:
            yield f"after:{date_from.strftime(_DATE_FORMAT)}"
        if date_to is not None:
            yield f"before:{date_to.strftime(_DATE_FORMAT)}"

    @staticmethod
    def _quoted(value: str) -> str:
        """Quote a value carrying spaces, so it stays one term."""
        cleaned = value.replace('"', "")
        return f'"{cleaned}"' if " " in cleaned else cleaned
