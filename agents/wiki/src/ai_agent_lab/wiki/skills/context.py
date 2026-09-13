"""Assembly of the untrusted context handed to a reasoner.

Turning pages into reasoning context is shared by summarisation, answering and
gap analysis, so it lives in one place. Sections keep the :class:`UntrustedText`
wrapper all the way to the prompt envelope, which is the only component allowed
to render them.

The budget matters more here than it does for mail. A wiki page is routinely tens
of thousands of characters, and three of them would fill a context window on
their own. Two limits are applied rather than one: each page is truncated, and
the number of pages is capped. Truncating alone would let a hundred short pages
through; capping alone would let one enormous page through.
"""

from __future__ import annotations

from collections.abc import Iterable

from ygo74.agent_runtime.domains.security.untrusted import UntrustedText, untrusted

from ai_agent_lab.core.reasoning.ports import UntrustedSection
from ai_agent_lab.wiki.domain.models import WikiComment, WikiPage
from ai_agent_lab.wiki.domain.origins import WikiOrigin

TRUNCATION_NOTICE = "\n[... truncated ...]"

DEFAULT_MAX_PAGE_CHARACTERS = 6000
DEFAULT_MAX_PAGES = 8
DEFAULT_MAX_COMMENT_CHARACTERS = 1000


class WikiContextBuilder:
    """Builds labelled untrusted sections out of pages.

    Args:
        max_page_characters: Upper bound applied to each page body. Bodies are
            truncated rather than dropped, so a long reference page cannot push
            the rest of the retrieved documentation out of the window.
        max_pages: Upper bound on how many pages reach one prompt.
        max_comment_characters: Upper bound applied to each comment body.
    """

    def __init__(
        self,
        *,
        max_page_characters: int = DEFAULT_MAX_PAGE_CHARACTERS,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_comment_characters: int = DEFAULT_MAX_COMMENT_CHARACTERS,
    ) -> None:
        self._max_page_characters = max_page_characters
        self._max_pages = max_pages
        self._max_comment_characters = max_comment_characters

    def build(self, pages: Iterable[WikiPage]) -> tuple[UntrustedSection, ...]:
        """Build one section per page, preserving the given order.

        The order is the caller's: a search hands over its results by relevance,
        and truncating the tail of that is the least damaging way to stay within
        budget.
        """
        return tuple(self._section_for(page) for page in list(pages)[: self._max_pages])

    def build_with_discussion(
        self,
        page: WikiPage,
        comments: Iterable[WikiComment],
    ) -> tuple[UntrustedSection, ...]:
        """Build the sections of one page and of its discussion.

        Comments are separate sections rather than appended to the body. A
        comment often contradicts the page it hangs off - "this was never
        funded" - and merging the two would present the objection as part of the
        documentation.
        """
        sections = [self._section_for(page)]
        sections.extend(self._comment_section(comment) for comment in comments)
        return tuple(sections)

    def _section_for(self, page: WikiPage) -> UntrustedSection:
        """Build the section describing a single page."""
        return UntrustedSection(label=self._label_for(page), content=self._content_of(page))

    @staticmethod
    def _label_for(page: WikiPage) -> str:
        """Build a label made only of trusted metadata.

        The label carries identifiers, a version and a timestamp, never
        third-party text, so it cannot become an injection vector of its own. A
        page title would be exactly such a vector, and it is already inside the
        fenced content where it belongs.
        """
        return (
            f"page_id={page.page_id} space={page.space_key} version={page.version} "
            f"last_modified={page.last_modified_at.isoformat()} status={page.status.value}"
        )

    def _content_of(self, page: WikiPage) -> UntrustedText:
        """Merge the title and body of a page into one untrusted block.

        Exposing the fragments here is deliberate and local: the result is
        immediately re-wrapped, so the merged text never escapes the untrusted
        world.
        """
        lines = [
            f"Title: {page.title.expose()}",
            f"Format: {page.body_format.value}",
            "",
            self._truncate(page.body.expose(), self._max_page_characters),
        ]
        return untrusted("\n".join(lines), WikiOrigin.PAGE_BODY)

    def _comment_section(self, comment: WikiComment) -> UntrustedSection:
        """Build the section describing one comment."""
        label = f"comment_id={comment.comment_id} page_id={comment.page_id} created={comment.created_at.isoformat()}"
        body = self._truncate(comment.body.expose(), self._max_comment_characters)
        return UntrustedSection(
            label=label,
            content=untrusted(body, WikiOrigin.COMMENT_BODY),
        )

    @staticmethod
    def _truncate(text: str, budget: int) -> str:
        """Shorten text that exceeds the configured budget."""
        if len(text) <= budget:
            return text
        return text[:budget] + TRUNCATION_NOTICE
