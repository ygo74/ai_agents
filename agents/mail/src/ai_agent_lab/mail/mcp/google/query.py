"""Translation of a structured mailbox query into Gmail search syntax.

Gmail takes a single query string. Building it is deterministic work - operator
names, quoting, date formatting - so it is done in code rather than asked of a
model, and it is tested on its own.

Labels are the one criterion that cannot be rendered from the request alone.
Gmail's ``label:`` operator matches the name a person reads, while the domain
carries identifiers, so the caller resolves the names first and passes them in.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from datetime import datetime

from ai_agent_lab.mail.domain.models import MailSearchRequest

_DATE_FORMAT = "%Y/%m/%d"
_logger = logging.getLogger(__name__)


class GmailQueryBuilder:
    """Renders a structured request as a Gmail query string."""

    def build(self, request: MailSearchRequest, label_names: Mapping[str, str] | None = None) -> str:
        """Return the query Gmail should evaluate.

        Args:
            request: The criteria to render.
            label_names: Label name for each identifier the request filters on.
                An identifier with no name is dropped rather than sent as-is:
                ``label:Label_3`` matches nothing, so passing it through would
                turn "no such label" into "no such message".
        """
        _logger.info("Building Gmail MCP search query")
        _logger.debug(
            "GmailQueryBuilder.build arguments: sender_present=%s, recipient_present=%s, "
            "subject_length=%s, keywords_length=%s, label_count=%d, unread_only=%s, "
            "attachment_filter=%s, date_from_present=%s, date_to_present=%s, "
            "resolved_label_count=%d",
            request.sender is not None,
            request.recipient is not None,
            None if request.subject_contains is None else len(request.subject_contains),
            None if request.keywords is None else len(request.keywords),
            len(request.label_ids),
            request.unread_only,
            request.has_attachments,
            request.date_from is not None,
            request.date_to is not None,
            len(label_names or {}),
        )
        return " ".join(self._terms(request, label_names or {})).strip()

    def _terms(self, request: MailSearchRequest, label_names: Mapping[str, str]) -> Iterator[str]:
        """Yield one term per active criterion."""
        _logger.debug(
            "GmailQueryBuilder._terms arguments: request_type=%s, resolved_label_count=%d",
            type(request).__name__,
            len(label_names),
        )
        yield from self._envelope_terms(request)
        yield from self._state_terms(request, label_names)

    def _envelope_terms(self, request: MailSearchRequest) -> Iterator[str]:
        """Yield the terms bearing on who wrote what."""
        _logger.debug(
            "GmailQueryBuilder._envelope_terms arguments: sender_present=%s, "
            "recipient_present=%s, subject_present=%s, keywords_present=%s",
            request.sender is not None,
            request.recipient is not None,
            bool(request.subject_contains),
            bool(request.keywords),
        )
        if request.sender is not None:
            yield f"from:{request.sender.value}"
        if request.recipient is not None:
            yield f"to:{request.recipient.value}"
        if request.subject_contains:
            yield f"subject:{self._quoted(request.subject_contains)}"
        if request.keywords:
            yield request.keywords

    def _state_terms(self, request: MailSearchRequest, label_names: Mapping[str, str]) -> Iterator[str]:
        """Yield the terms bearing on state, labels and dates."""
        _logger.debug(
            "GmailQueryBuilder._state_terms arguments: label_count=%d, "
            "resolved_label_count=%d, unread_only=%s, attachment_filter=%s, "
            "date_from_present=%s, date_to_present=%s",
            len(request.label_ids),
            len(label_names),
            request.unread_only,
            request.has_attachments,
            request.date_from is not None,
            request.date_to is not None,
        )
        for label_id in request.label_ids:
            name = label_names.get(label_id)
            if name:
                yield f"label:{self._quoted(name)}"
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
        _logger.debug("GmailQueryBuilder._quoted arguments: value_length=%d", len(value))
        cleaned = value.replace('"', "")
        return f'"{cleaned}"' if " " in cleaned else cleaned

    @staticmethod
    def _day(moment: datetime) -> str:
        """Render a bound as the day Gmail compares against."""
        _logger.debug("GmailQueryBuilder._day arguments: moment=%s", moment.isoformat())
        return moment.strftime(_DATE_FORMAT)
