"""Translation of a mailbox query into Gmail search syntax.

The protocol carries a query as separate criteria; Gmail takes a single string.
Building it is deterministic work - operator names, quoting, date formatting -
so it lives in code and is tested on its own.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
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
        label_ids: Sequence[str] = (),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        unread_only: bool = False,
        has_attachments: bool | None = None,
    ) -> str:
        """Return the query Gmail should evaluate."""
        terms = (
            *self._envelope(keywords, sender, recipient, subject_contains),
            *self._state(label_ids, unread_only, has_attachments, date_from, date_to),
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
        label_ids: Sequence[str],
        unread_only: bool,
        has_attachments: bool | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> Iterator[str]:
        """Yield the terms bearing on state, labels and dates."""
        for label_id in label_ids:
            yield f"label:{self._quoted(label_id)}"
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
