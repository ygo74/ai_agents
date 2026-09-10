"""Conversion of model-supplied arguments into domain requests.

A model fills in a schema; the domain needs a validated request. The translation
is small but it is where a malformed date or an unknown ordering is caught, so it
lives in one place rather than inside each capability.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_agent_lab.wiki.capabilities.tool_inputs import SearchWikiInput
from ai_agent_lab.wiki.domain.errors import WikiDomainError
from ai_agent_lab.wiki.domain.models import WikiSearchRequest


class InvalidSearchArgumentError(WikiDomainError):
    """Raised when a model supplied a search argument the domain cannot use."""

    def __init__(self, field: str, value: str) -> None:
        super().__init__(f"{field} must be an ISO-8601 date or date-time, got {value!r}")
        self.field = field


class WikiSearchRequestFactory:
    """Builds a domain search request from what a model supplied."""

    def build(self, payload: SearchWikiInput) -> WikiSearchRequest:
        """Return the validated request a capability will run."""
        return WikiSearchRequest(
            text=payload.text.strip(),
            space_keys=payload.space_keys,
            labels=payload.labels,
            title_contains=payload.title_contains.strip(),
            modified_after=self._moment(payload.modified_after, "modified_after"),
            modified_before=self._moment(payload.modified_before, "modified_before"),
            statuses=payload.statuses,
            sort_order=payload.sort_order,
            limit=payload.limit,
        )

    @staticmethod
    def _moment(value: str | None, field: str) -> datetime | None:
        """Parse an optional timestamp a model supplied.

        A date without a time zone is read as UTC rather than refused: a model
        asked for "pages changed since June" will write ``2026-06-01``, and
        turning that into an error would be pedantry rather than safety.
        """
        if value is None or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as error:
            raise InvalidSearchArgumentError(field, value) from error
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
