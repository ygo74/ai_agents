"""Translation between tool inputs and domain requests."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_agent_lab.mail.capabilities.tool_inputs import SearchMailInput
from ai_agent_lab.mail.domain.models import EmailAddress, MailSearchRequest


class MailSearchRequestFactory:
    """Builds a domain search request out of a tool input.

    Parsing and validation happen here rather than inside the skill, so an
    invalid date proposed by a model fails at the boundary with a clear reason
    instead of reaching the MCP layer.
    """

    def build(self, payload: SearchMailInput) -> MailSearchRequest:
        """Convert a tool input into a validated search request."""
        return MailSearchRequest(
            keywords=payload.keywords,
            sender=self._address(payload.sender),
            recipient=self._address(payload.recipient),
            subject_contains=payload.subject_contains,
            label_ids=tuple(payload.label_ids),
            date_from=self._timestamp(payload.date_from),
            date_to=self._timestamp(payload.date_to),
            unread_only=payload.unread_only,
            has_attachments=payload.has_attachments,
            limit=payload.limit,
            sort_order=payload.sort_order,
        )

    @staticmethod
    def _address(value: str | None) -> EmailAddress | None:
        """Parse an optional email address."""
        return None if not value else EmailAddress(value=value)

    @staticmethod
    def _timestamp(value: str | None) -> datetime | None:
        """Parse an optional ISO-8601 bound, assuming UTC when no zone is given."""
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
