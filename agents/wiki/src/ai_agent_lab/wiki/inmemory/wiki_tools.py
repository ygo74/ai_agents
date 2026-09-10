"""Deterministic implementation of the wiki MCP contract.

It exists so the agent, the skills and the confirmation model can be exercised
end to end without Confluence, without credentials and without a network.

It is not a shortcut around the architecture: it sits exactly where a real MCP
client sits and honours the same contract, validated by the same conformance
suite. In particular it enforces the same per-space and per-page restrictions a
wiki does, so an authorisation test run against it means something.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.wiki.domain.enums import WikiContentFormat, WikiSortOrder
from ai_agent_lab.wiki.domain.models import (
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageReference,
    WikiPageTree,
    WikiPageVersion,
    WikiSearchRequest,
    WikiSearchResult,
    WikiSpace,
)
from ai_agent_lab.wiki.inmemory.wiki import PageEntry, Wiki
from ai_agent_lab.wiki.wiki_errors import WikiConcurrentEditError, WikiNotFoundError

EXCERPT_LENGTH = 200


class InMemoryWikiTools:
    """Implements :class:`WikiTools` against an in-memory wiki."""

    def __init__(self, wiki: Wiki) -> None:
        self._wiki = wiki

    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult:
        """Return the readable page references matching a query."""
        matches = [page for page in self._wiki.readable_pages(user.user_id) if self._matches(page, request)]
        ordered = self._ordered(matches, request.sort_order)
        selected = ordered[: request.limit]
        return WikiSearchResult(
            references=tuple(self._reference(page) for page in selected),
            total_count=len(ordered),
            truncated=len(ordered) > len(selected),
        )

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        """Return one complete page."""
        return self._wiki.page(page_id, user.user_id)

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        """Return the direct children of a page."""
        children = self._wiki.children_of(page_id, user.user_id)
        ordered = sorted(children, key=lambda page: page.title.expose().casefold())
        return WikiPageTree(
            parent_id=page_id,
            children=tuple(page.to_reference() for page in ordered),
        )

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        """Return the spaces this user may read."""
        spaces = self._wiki.readable_spaces(user.user_id)
        return tuple(sorted(spaces, key=lambda space: space.key))

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        """Return the comments attached to a page, oldest first."""
        comments = self._wiki.comments(page_id, user.user_id)
        return tuple(sorted(comments, key=lambda comment: comment.created_at))

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        """Return the revision history of a page, newest first."""
        return self._wiki.history(page_id, user.user_id)

    async def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        user: UserContext,
        *,
        parent_id: str | None = None,
    ) -> WikiPage:
        """Create a page and return it as stored."""
        if not self._wiki.has_space(space_key):
            raise WikiNotFoundError("space", space_key)
        if parent_id is not None:
            self._wiki.page(parent_id, user.user_id)

        now = datetime.now(UTC)
        page = WikiPage(
            page_id=f"page-{uuid.uuid4().hex[:8]}",
            space_key=space_key,
            title=untrusted(title, UntrustedOrigin.WIKI_PAGE_TITLE),
            body=untrusted(body, UntrustedOrigin.WIKI_PAGE_BODY),
            body_format=WikiContentFormat.MARKDOWN,
            parent_id=parent_id,
            created_at=now,
            last_modified_at=now,
            version=1,
        )
        self._wiki.store(PageEntry(page, history=self._initial_history(page, now)))
        return page

    async def update_page(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        title: str | None = None,
        expected_version: int | None = None,
    ) -> WikiPage:
        """Replace the body of a page and return the new revision."""
        entry = self._wiki.entry(page_id, user.user_id)
        self._require_current_version(entry.page, expected_version)

        now = datetime.now(UTC)
        updated = entry.page.model_copy(
            update={
                "body": untrusted(body, UntrustedOrigin.WIKI_PAGE_BODY),
                "title": (
                    entry.page.title if title is None else untrusted(title, UntrustedOrigin.WIKI_PAGE_TITLE)
                ),
                "last_modified_at": now,
                "version": entry.page.version + 1,
            }
        )
        self._wiki.store(
            PageEntry(
                updated,
                comments=entry.comments,
                history=self._extended_history(entry.history, entry.page, updated, now),
                restricted_to=entry.restricted_to,
            )
        )
        return updated

    async def delete_page(self, page_id: str, user: UserContext) -> None:
        """Delete a page."""
        self._wiki.entry(page_id, user.user_id)
        self._wiki.remove(page_id)

    async def add_comment(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        parent_comment_id: str | None = None,
    ) -> WikiComment:
        """Post a comment on a page and return it as stored."""
        entry = self._wiki.entry(page_id, user.user_id)
        self._require_known_comment(entry, parent_comment_id)

        comment = WikiComment(
            comment_id=f"comment-{uuid.uuid4().hex[:8]}",
            page_id=page_id,
            body=untrusted(body, UntrustedOrigin.WIKI_COMMENT_BODY),
            created_at=datetime.now(UTC),
            parent_comment_id=parent_comment_id,
        )
        self._wiki.store(
            PageEntry(
                entry.page,
                comments=(*entry.comments, comment),
                history=entry.history,
                restricted_to=entry.restricted_to,
            )
        )
        return comment

    @staticmethod
    def _require_current_version(page: WikiPage, expected_version: int | None) -> None:
        """Refuse a write based on a revision somebody has since replaced.

        Without this, an agent that read a page, thought about it, and wrote it
        back would silently discard whatever a colleague did in between.
        """
        if expected_version is None or expected_version == page.version:
            return
        raise WikiConcurrentEditError(page.page_id, expected_version, page.version)

    @staticmethod
    def _require_known_comment(entry: PageEntry, parent_comment_id: str | None) -> None:
        """Refuse a reply to a comment that is not on this page."""
        if parent_comment_id is None:
            return
        if any(comment.comment_id == parent_comment_id for comment in entry.comments):
            return
        raise WikiNotFoundError("comment", parent_comment_id)

    @staticmethod
    def _initial_history(page: WikiPage, moment: datetime) -> WikiPageHistory:
        """Build the one-entry history of a freshly created page."""
        return WikiPageHistory(
            page_id=page.page_id,
            versions=(WikiPageVersion(version=1, modified_at=moment),),
        )

    @staticmethod
    def _extended_history(
        history: WikiPageHistory | None,
        previous: WikiPage,
        page: WikiPage,
        moment: datetime,
    ) -> WikiPageHistory:
        """Prepend the new revision to a page's history, newest first.

        A page with no recorded history still had a revision before this write.
        Starting from an empty list would erase it, and the history would then
        claim the page sprang into existence at its current version.
        """
        entry = WikiPageVersion(version=page.version, modified_at=moment)
        if history is not None:
            return WikiPageHistory(page_id=page.page_id, versions=(entry, *history.versions))

        seed = WikiPageVersion(
            version=previous.version,
            modified_at=previous.last_modified_at,
            modified_by=previous.last_modified_by,
        )
        return WikiPageHistory(page_id=page.page_id, versions=(entry, seed))

    @staticmethod
    def _reference(page: WikiPage) -> WikiPageReference:
        """Project a page onto a search reference, excerpt included."""
        return page.to_reference().model_copy(
            update={
                "excerpt": untrusted(
                    page.body.expose()[:EXCERPT_LENGTH],
                    UntrustedOrigin.WIKI_PAGE_EXCERPT,
                )
            }
        )

    def _matches(self, page: WikiPage, request: WikiSearchRequest) -> bool:
        """Whether a page satisfies every constraint of a request."""
        return (
            self._matches_status(page, request)
            and self._matches_space(page, request)
            and self._matches_window(page, request)
            and self._matches_text(page, request)
            and self._matches_title(page, request)
            and self._matches_labels(page, request)
        )

    @staticmethod
    def _matches_status(page: WikiPage, request: WikiSearchRequest) -> bool:
        """Whether the page is in one of the requested publication states."""
        return not request.statuses or page.status in request.statuses

    @staticmethod
    def _matches_space(page: WikiPage, request: WikiSearchRequest) -> bool:
        """Whether the page lives in one of the requested spaces."""
        return not request.space_keys or page.space_key in request.space_keys

    @staticmethod
    def _matches_window(page: WikiPage, request: WikiSearchRequest) -> bool:
        """Whether the page was modified inside the requested window."""
        if request.modified_after is not None and page.last_modified_at < request.modified_after:
            return False
        return not (request.modified_before is not None and page.last_modified_at > request.modified_before)

    @staticmethod
    def _matches_text(page: WikiPage, request: WikiSearchRequest) -> bool:
        """Whether the free-text terms all appear in the title or the body."""
        terms = request.text.casefold().split()
        if not terms:
            return True
        haystack = f"{page.title.expose()}\n{page.body.expose()}".casefold()
        return all(term in haystack for term in terms)

    @staticmethod
    def _matches_title(page: WikiPage, request: WikiSearchRequest) -> bool:
        """Whether the title contains the requested fragment."""
        fragment = request.title_contains.casefold().strip()
        return not fragment or fragment in page.title.expose().casefold()

    @staticmethod
    def _matches_labels(page: WikiPage, request: WikiSearchRequest) -> bool:
        """Whether the page carries every requested label."""
        if not request.labels:
            return True
        carried = {label.expose().casefold() for label in page.labels}
        return all(label.casefold() in carried for label in request.labels)

    @staticmethod
    def _ordered(pages: list[WikiPage], order: WikiSortOrder) -> list[WikiPage]:
        """Sort matches as the request asked.

        Relevance has no meaning without a scoring engine, so it falls back to
        the most recently modified. Pretending otherwise would make the ordering
        of the mock differ from every real server for no stated reason.
        """
        if order is WikiSortOrder.TITLE:
            return sorted(pages, key=lambda page: page.title.expose().casefold())
        if order is WikiSortOrder.CREATED:
            return sorted(pages, key=lambda page: page.created_at, reverse=True)
        return sorted(pages, key=lambda page: page.last_modified_at, reverse=True)
