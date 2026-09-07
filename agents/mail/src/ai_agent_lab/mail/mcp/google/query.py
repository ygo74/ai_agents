"""Translation of a structured mailbox query into Gmail search syntax.

Gmail takes a single query string. Building it is deterministic work - operator
names, quoting, date formatting - so it is done in code rather than asked of a
model, and it is tested on its own.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from ai_agent_lab.mail.domain.models import MailSearchRequest

_DATE_FORMAT = "%Y/%m/%d"


class GmailQueryBuilder:
    """Renders a structured request as a Gmail query string."""

    def build(self, request: MailSearchRequest) -> str:
        """Return the query Gmail should evaluate."""
        return " ".join(self._terms(request)).strip()

    def _terms(self, request: MailSearchRequest) -> Iterator[str]:
        """Yield one term per active criterion."""
        yield from self._envelope_terms(request)
        yield from self._state_terms(request)

    def _envelope_terms(self, request: MailSearchRequest) -> Iterator[str]:
        """Yield the terms bearing on who wrote what."""
        if request.sender is not None:
            yield f"from:{request.sender.value}"
        if request.recipient is not None:
            yield f"to:{request.recipient.value}"
        if request.subject_contains:
            yield f"subject:{self._quoted(request.subject_contains)}"
        if request.keywords:
            yield request.keywords

    def _state_terms(self, request: MailSearchRequest) -> Iterator[str]:
        """Yield the terms bearing on state, labels and dates."""
        for label_id in request.label_ids:
            yield f"label:{self._quoted(label_id)}"
        if request.unread_only:
            yield "is:unread"
        if request.has_attachments is True:
            yield "has:attachment"
        if request.has_attachments is False:
            yield "-has:attachment"
        if request.date_from is not None:
            yield f"after:{self._day(request.date_from)}"
        if request.date_to is not None:
            yield f"before:{self._day(request.date_to)}"

    @staticmethod
    def _quoted(value: str) -> str:
        """Quote a value carrying spaces, so it stays one term."""
        cleaned = value.replace('"', "")
        return f'"{cleaned}"' if " " in cleaned else cleaned

    @staticmethod
    def _day(moment: datetime) -> str:
        """Render a bound as the day Gmail compares against."""
        return moment.strftime(_DATE_FORMAT)
