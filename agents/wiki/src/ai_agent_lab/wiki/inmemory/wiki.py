"""Deterministic wiki used by the mock runtime mode and by the tests.

This is an in-memory store honouring the same access rules a real wiki does,
which is the part that matters. A fake that let every user read every page would
make the authorisation tests pass by construction and prove nothing: on a wiki,
"you may not read this" is a normal, frequent answer, not an incident.

Two levels of restriction are modelled, because Confluence has both:

* a **space** may be readable by an explicit set of accounts;
* a **page** may be restricted further, to fewer accounts than its space.

An empty set means "anyone who reaches this far", so the ordinary case stays
simple to express in a dataset.
"""

from __future__ import annotations

from collections.abc import Iterable

from ai_agent_lab.wiki.domain.models import (
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiSpace,
)
from ai_agent_lab.wiki.wiki_errors import WikiAccessDeniedError, WikiNotFoundError


class SpaceEntry:
    """One space and who may read it."""

    def __init__(self, space: WikiSpace, readable_by: Iterable[str] = ()) -> None:
        self.space = space
        self.readable_by = frozenset(readable_by)

    def is_readable_by(self, account_id: str) -> bool:
        """Whether an account may read this space."""
        return not self.readable_by or account_id in self.readable_by


class PageEntry:
    """One page, its discussion, its history and who may read it."""

    def __init__(
        self,
        page: WikiPage,
        comments: Iterable[WikiComment] = (),
        history: WikiPageHistory | None = None,
        restricted_to: Iterable[str] = (),
    ) -> None:
        self.page = page
        self.comments = tuple(comments)
        self.history = history
        self.restricted_to = frozenset(restricted_to)

    def is_readable_by(self, account_id: str) -> bool:
        """Whether an account may read this page, ignoring its space."""
        return not self.restricted_to or account_id in self.restricted_to


class Wiki:
    """The spaces and pages of one deterministic wiki."""

    def __init__(self, spaces: Iterable[SpaceEntry] = (), pages: Iterable[PageEntry] = ()) -> None:
        self._spaces: dict[str, SpaceEntry] = {entry.space.key: entry for entry in spaces}
        self._pages: dict[str, PageEntry] = {entry.page.page_id: entry for entry in pages}

    @property
    def pages(self) -> tuple[PageEntry, ...]:
        """Every page currently stored, readable or not."""
        return tuple(self._pages.values())

    @property
    def spaces(self) -> tuple[SpaceEntry, ...]:
        """Every space currently stored, readable or not."""
        return tuple(self._spaces.values())

    def readable_spaces(self, account_id: str) -> tuple[WikiSpace, ...]:
        """Return the spaces this account may read."""
        return tuple(entry.space for entry in self._spaces.values() if entry.is_readable_by(account_id))

    def readable_pages(self, account_id: str) -> tuple[WikiPage, ...]:
        """Return every page this account may read.

        A search must never surface a page the user cannot open. Filtering here,
        rather than in each query, is what makes that hold for every filter
        combination rather than for the ones somebody remembered.
        """
        return tuple(entry.page for entry in self._pages.values() if self._may_read(entry, account_id))

    def page(self, page_id: str, account_id: str) -> WikiPage:
        """Return a page this account may read, or fail."""
        return self._entry(page_id, account_id).page

    def comments(self, page_id: str, account_id: str) -> tuple[WikiComment, ...]:
        """Return the comments of a page this account may read."""
        return self._entry(page_id, account_id).comments

    def history(self, page_id: str, account_id: str) -> WikiPageHistory:
        """Return the revision history of a page this account may read."""
        entry = self._entry(page_id, account_id)
        if entry.history is None:
            raise WikiNotFoundError("history of page", page_id)
        return entry.history

    def children_of(self, page_id: str, account_id: str) -> tuple[WikiPage, ...]:
        """Return the readable direct children of a page.

        The parent itself must be readable first: answering "this page has three
        children" to somebody who may not open the parent already leaks its
        shape.
        """
        self._entry(page_id, account_id)
        return tuple(
            entry.page
            for entry in self._pages.values()
            if entry.page.parent_id == page_id and self._may_read(entry, account_id)
        )

    def store(self, entry: PageEntry) -> None:
        """Add or replace a page."""
        self._pages[entry.page.page_id] = entry

    def remove(self, page_id: str) -> None:
        """Delete a page."""
        self._pages.pop(page_id, None)

    def has_space(self, space_key: str) -> bool:
        """Whether a space exists, regardless of who may read it."""
        return space_key in self._spaces

    def entry(self, page_id: str, account_id: str) -> PageEntry:
        """Return the full entry of a page this account may read."""
        return self._entry(page_id, account_id)

    def _entry(self, page_id: str, account_id: str) -> PageEntry:
        """Resolve a page, distinguishing absence from refusal.

        The two answers are kept apart deliberately. Reporting a restricted page
        as missing would be a comfortable lie that makes an agent tell users the
        documentation does not exist when in fact they may not see it.
        """
        entry = self._pages.get(page_id)
        if entry is None:
            raise WikiNotFoundError("page", page_id)
        if not self._may_read(entry, account_id):
            raise WikiAccessDeniedError(page_id)
        return entry

    def _may_read(self, entry: PageEntry, account_id: str) -> bool:
        """Whether an account may read a page, space restrictions included."""
        space = self._spaces.get(entry.page.space_key)
        if space is not None and not space.is_readable_by(account_id):
            return False
        return entry.is_readable_by(account_id)
