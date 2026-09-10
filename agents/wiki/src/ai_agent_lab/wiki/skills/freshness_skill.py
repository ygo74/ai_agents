"""Deterministic assessment of how current documentation is.

Nothing here asks a language model anything, and that is the point. Whether a
page has not been touched for two hundred days is a subtraction of two dates. It
has exactly one right answer, it is the same answer every time, and a model would
give a plausible one at a cost, with a chance of being wrong.

The thresholds are injected rather than fixed. What counts as stale is a
judgement about a particular body of documentation - a coding standard ages
slowly, a sprint plan ages in weeks - so it belongs to configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.untrusted import UntrustedText
from ai_agent_lab.wiki.domain.enums import WikiFreshness
from ai_agent_lab.wiki.domain.models import (
    WikiFreshnessReport,
    WikiPage,
    WikiPageFreshness,
    WikiPageReference,
    WikiSearchRequest,
)
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.skills.errors import EmptyPageSelectionError
from ai_agent_lab.wiki.tools_port import WikiReadTools

DEFAULT_AGEING_AFTER_DAYS = 90
DEFAULT_STALE_AFTER_DAYS = 180

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    """Return the current instant, always timezone-aware."""
    return datetime.now(UTC)


class PageFreshnessDetector:
    """Decides how current a page is, from its last modification date.

    It judges a whole page and a search reference alike: both carry a
    modification date, a version and a title, and that is everything the rule
    needs. Accepting only whole pages would have forced a caller assessing search
    results to download every body in order to compute a subtraction.

    Args:
        ageing_after_days: Beyond this, a page is worth a second look.
        stale_after_days: Beyond this, a page should not be trusted without
            checking it against reality.
        clock: Injected so the rule is testable without waiting.
    """

    def __init__(
        self,
        *,
        ageing_after_days: int = DEFAULT_AGEING_AFTER_DAYS,
        stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
        clock: Clock = _utc_now,
    ) -> None:
        if ageing_after_days < 1:
            raise ValueError("a page cannot be ageing before it exists")
        if stale_after_days <= ageing_after_days:
            raise ValueError("a page must be ageing before it is stale")
        self._ageing_after_days = ageing_after_days
        self._stale_after_days = stale_after_days
        self._clock = clock

    def assess(self, page: WikiPage) -> WikiPageFreshness:
        """Judge one complete page."""
        return self.judge(
            page_id=page.page_id,
            title=page.title,
            last_modified_at=page.last_modified_at,
            version=page.version,
        )

    def assess_reference(self, reference: WikiPageReference) -> WikiPageFreshness:
        """Judge one search reference, without fetching its body."""
        return self.judge(
            page_id=reference.page_id,
            title=reference.title,
            last_modified_at=reference.last_modified_at,
            version=reference.version,
        )

    def judge(
        self,
        *,
        page_id: str,
        title: UntrustedText,
        last_modified_at: datetime,
        version: int,
    ) -> WikiPageFreshness:
        """Apply the rule to the four facts it needs."""
        days = self._days_since(last_modified_at)
        return WikiPageFreshness(
            page_id=page_id,
            title=title,
            freshness=self._freshness(days),
            days_since_change=days,
            last_modified_at=last_modified_at,
            version=version,
        )

    def report(self, assessed: Sequence[WikiPageFreshness]) -> WikiFreshnessReport:
        """Assemble a report, most stale first."""
        ordered = sorted(assessed, key=lambda entry: entry.days_since_change, reverse=True)
        return WikiFreshnessReport(pages=tuple(ordered), assessed_at=self._clock())

    def _days_since(self, moment: datetime) -> int:
        """Return whole days since a moment, never negative.

        A page whose timestamp is in the future is a clock skew between the wiki
        and this process, not a page edited tomorrow. Reporting a negative age
        would make every threshold comparison behave strangely.
        """
        elapsed = self._clock() - moment
        return max(elapsed.days, 0)

    def _freshness(self, days: int) -> WikiFreshness:
        """Apply the thresholds."""
        if days >= self._stale_after_days:
            return WikiFreshness.STALE
        if days >= self._ageing_after_days:
            return WikiFreshness.AGEING
        return WikiFreshness.FRESH


class PageFreshnessSkill:
    """Reports how current a body of documentation is."""

    def __init__(self, wiki_tools: WikiReadTools, detector: PageFreshnessDetector) -> None:
        self._wiki_tools = wiki_tools
        self._detector = detector

    async def assess_pages(self, page_ids: Sequence[str], user: UserContext) -> WikiFreshnessReport:
        """Judge an explicit set of pages."""
        user.require_permission(WikiPermission.READ)
        if not page_ids:
            raise EmptyPageSelectionError("PageFreshnessSkill")
        pages = [await self._wiki_tools.get_page(page_id, user) for page_id in page_ids]
        return self._detector.report([self._detector.assess(page) for page in pages])

    async def assess_search(self, request: WikiSearchRequest, user: UserContext) -> WikiFreshnessReport:
        """Judge the pages a search returns.

        The search already carries the modification date of every hit, so no page
        body is fetched. Assessing freshness by downloading a hundred pages would
        cost a great deal to compute a subtraction.
        """
        user.require_permission(WikiPermission.READ)
        result = await self._wiki_tools.search(request, user)
        return self._detector.report(
            [self._detector.assess_reference(reference) for reference in result.references]
        )
