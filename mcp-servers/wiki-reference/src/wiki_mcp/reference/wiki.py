"""A wiki built from a JSON dataset, expressed in protocol payloads.

The dataset format is the one delivered under ``data/wiki/``. It is read here
independently of the agent: this package must keep working with no
``ai_agent_lab`` installed at all, which is the whole point of the boundary.

Restrictions are reproduced faithfully. A double that let every account read
every page would let a client pass a conformance suite it would fail against a
real Confluence, where per-space and per-page restrictions are the norm.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wiki_mcp.protocol import payloads as wire
from wiki_mcp.protocol.errors import AccessDeniedError, ConflictError, NotFoundError, ProtocolError

JsonObject = Mapping[str, Any]

EXCERPT_LENGTH = 200


class PageRecord:
    """One page of the dataset, with its discussion, history and restrictions."""

    def __init__(
        self,
        page: wire.Page,
        comments: tuple[wire.Comment, ...] = (),
        history: wire.PageHistory | None = None,
        restricted_to: frozenset[str] = frozenset(),
    ) -> None:
        self.page = page
        self.comments = comments
        self.history = history
        self.restricted_to = restricted_to

    def is_readable_by(self, account: str) -> bool:
        """Whether an account may read this page, ignoring its space."""
        return not self.restricted_to or account in self.restricted_to


class SpaceRecord:
    """One space of the dataset and who may read it."""

    def __init__(self, space: wire.Space, readable_by: frozenset[str] = frozenset()) -> None:
        self.space = space
        self.readable_by = readable_by

    def is_readable_by(self, account: str) -> bool:
        """Whether an account may read this space."""
        return not self.readable_by or account in self.readable_by


class WikiDataset:
    """Every space and page the server holds."""

    def __init__(self, spaces: Sequence[SpaceRecord], pages: Sequence[PageRecord]) -> None:
        self.spaces = {record.space.key: record for record in spaces}
        self.pages = {record.page.page_id: record for record in pages}

    def may_read(self, record: PageRecord, account: str) -> bool:
        """Whether an account may read a page, space restrictions included."""
        space = self.spaces.get(record.page.space_key)
        if space is not None and not space.is_readable_by(account):
            return False
        return record.is_readable_by(account)

    def resolve(self, account: str) -> AccountWiki:
        """Return the wiki as one account sees it."""
        return AccountWiki(self, account)


class AccountWiki:
    """The dataset as seen by one account.

    Every read goes through the restriction check, so a filter nobody thought of
    cannot become a way around it.
    """

    def __init__(self, dataset: WikiDataset, account: str) -> None:
        self._dataset = dataset
        self._account = account

    async def search(
        self,
        *,
        text: str | None = None,
        space_keys: Sequence[str] = (),
        labels: Sequence[str] = (),
        title_contains: str | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        statuses: Sequence[str] = (),
        sort_order: wire.SortOrder = wire.SortOrder.RELEVANCE,
        limit: int = 10,
    ) -> wire.SearchResult:
        """Return the readable page references matching a query."""
        wanted = tuple(statuses) or (wire.PageStatus.CURRENT.value,)
        matches = [
            record.page
            for record in self._dataset.pages.values()
            if self._dataset.may_read(record, self._account)
            and _matches(
                record.page,
                text=text,
                space_keys=tuple(space_keys),
                labels=tuple(labels),
                title_contains=title_contains,
                modified_after=modified_after,
                modified_before=modified_before,
                statuses=wanted,
            )
        ]
        ordered = _ordered(matches, sort_order)
        selected = ordered[:limit]
        return wire.SearchResult(
            references=tuple(_reference(page) for page in selected),
            total_count=len(ordered),
            truncated=len(ordered) > len(selected),
        )

    async def get_page(self, page_id: str) -> wire.Page:
        """Return one complete page."""
        return self._record(page_id).page

    async def get_children(self, page_id: str) -> wire.PageTree:
        """Return the readable direct children of a page."""
        self._record(page_id)
        children = [
            record.page
            for record in self._dataset.pages.values()
            if record.page.parent_id == page_id and self._dataset.may_read(record, self._account)
        ]
        ordered = sorted(children, key=lambda page: page.title.casefold())
        return wire.PageTree(parent_id=page_id, children=tuple(_reference(page) for page in ordered))

    async def list_spaces(self) -> wire.SpaceList:
        """Return the spaces this account may read."""
        readable = [
            record.space for record in self._dataset.spaces.values() if record.is_readable_by(self._account)
        ]
        return wire.SpaceList(spaces=tuple(sorted(readable, key=lambda space: space.key)))

    async def get_comments(self, page_id: str) -> wire.CommentList:
        """Return the comments attached to a page, oldest first."""
        comments = self._record(page_id).comments
        return wire.CommentList(comments=tuple(sorted(comments, key=lambda comment: comment.created_at)))

    async def get_history(self, page_id: str) -> wire.PageHistory:
        """Return the revision history of a page, newest first."""
        record = self._record(page_id)
        if record.history is None:
            raise NotFoundError("history of page", page_id)
        return record.history

    async def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
    ) -> wire.Page:
        """Create a page and return it as stored."""
        space = self._dataset.spaces.get(space_key)
        if space is None:
            raise NotFoundError("space", space_key)
        if not space.is_readable_by(self._account):
            raise AccessDeniedError(f"space {space_key!r} is not readable by {self._account!r}")
        if parent_id is not None:
            self._record(parent_id)

        now = datetime.now(UTC)
        page = wire.Page(
            page_id=f"page-{uuid.uuid4().hex[:8]}",
            space_key=space_key,
            title=title,
            body=body,
            parent_id=parent_id,
            created_at=now,
            last_modified_at=now,
            version=1,
        )
        self._dataset.pages[page.page_id] = PageRecord(
            page,
            history=wire.PageHistory(
                page_id=page.page_id,
                versions=(wire.PageVersion(version=1, modified_at=now),),
            ),
        )
        return page

    async def update_page(
        self,
        page_id: str,
        body: str,
        title: str | None = None,
        expected_version: int | None = None,
    ) -> wire.Page:
        """Replace the body of a page and return the new revision."""
        record = self._record(page_id)
        if expected_version is not None and expected_version != record.page.version:
            raise ConflictError(
                f"page {page_id!r} is at version {record.page.version}, not the expected "
                f"{expected_version}: somebody edited it in the meantime"
            )

        now = datetime.now(UTC)
        updated = record.page.model_copy(
            update={
                "body": body,
                "title": record.page.title if title is None else title,
                "last_modified_at": now,
                "version": record.page.version + 1,
            }
        )
        self._dataset.pages[page_id] = PageRecord(
            updated,
            comments=record.comments,
            history=_extended_history(record, updated, now),
            restricted_to=record.restricted_to,
        )
        return updated

    async def delete_page(self, page_id: str) -> None:
        """Delete a page."""
        self._record(page_id)
        self._dataset.pages.pop(page_id, None)

    async def add_comment(
        self,
        page_id: str,
        body: str,
        parent_comment_id: str | None = None,
    ) -> wire.Comment:
        """Post a comment on a page and return it as stored."""
        record = self._record(page_id)
        if parent_comment_id is not None and not any(
            comment.comment_id == parent_comment_id for comment in record.comments
        ):
            raise NotFoundError("comment", parent_comment_id)

        comment = wire.Comment(
            comment_id=f"comment-{uuid.uuid4().hex[:8]}",
            page_id=page_id,
            body=body,
            created_at=datetime.now(UTC),
            parent_comment_id=parent_comment_id,
        )
        self._dataset.pages[page_id] = PageRecord(
            record.page,
            comments=(*record.comments, comment),
            history=record.history,
            restricted_to=record.restricted_to,
        )
        return comment

    def _record(self, page_id: str) -> PageRecord:
        """Resolve a page, distinguishing absence from refusal."""
        record = self._dataset.pages.get(page_id)
        if record is None:
            raise NotFoundError("page", page_id)
        if not self._dataset.may_read(record, self._account):
            raise AccessDeniedError(f"page {page_id!r} is not readable by {self._account!r}")
        return record


def _extended_history(record: PageRecord, page: wire.Page, moment: datetime) -> wire.PageHistory:
    """Prepend the new revision to a page's history, newest first."""
    entry = wire.PageVersion(version=page.version, modified_at=moment)
    if record.history is not None:
        return wire.PageHistory(page_id=page.page_id, versions=(entry, *record.history.versions))
    seed = wire.PageVersion(version=record.page.version, modified_at=record.page.last_modified_at)
    return wire.PageHistory(page_id=page.page_id, versions=(entry, seed))


def _reference(page: wire.Page) -> wire.PageReference:
    """Project a page onto a search reference, excerpt included."""
    return wire.PageReference(
        page_id=page.page_id,
        space_key=page.space_key,
        title=page.title,
        excerpt=page.body[:EXCERPT_LENGTH],
        status=page.status,
        last_modified_at=page.last_modified_at,
        version=page.version,
        url=page.url,
    )


def _matches(
    page: wire.Page,
    *,
    text: str | None,
    space_keys: tuple[str, ...],
    labels: tuple[str, ...],
    title_contains: str | None,
    modified_after: datetime | None,
    modified_before: datetime | None,
    statuses: tuple[str, ...],
) -> bool:
    """Whether a page satisfies every constraint of a query."""
    if page.status.value not in statuses:
        return False
    if space_keys and page.space_key not in space_keys:
        return False
    if modified_after is not None and page.last_modified_at < modified_after:
        return False
    if modified_before is not None and page.last_modified_at > modified_before:
        return False
    if text and not _has_every_term(page, text):
        return False
    if title_contains and title_contains.casefold() not in page.title.casefold():
        return False
    carried = {label.casefold() for label in page.labels}
    return all(label.casefold() in carried for label in labels)


def _has_every_term(page: wire.Page, text: str) -> bool:
    """Whether every free-text term appears in the title or the body."""
    haystack = f"{page.title}\n{page.body}".casefold()
    return all(term in haystack for term in text.casefold().split())


def _ordered(pages: list[wire.Page], order: wire.SortOrder) -> list[wire.Page]:
    """Sort matches as the query asked."""
    if order is wire.SortOrder.TITLE:
        return sorted(pages, key=lambda page: page.title.casefold())
    if order is wire.SortOrder.CREATED:
        return sorted(pages, key=lambda page: page.created_at, reverse=True)
    return sorted(pages, key=lambda page: page.last_modified_at, reverse=True)


class WikiDatasetLoader:
    """Builds a dataset from the delivered JSON description."""

    def load(self, path: Path) -> WikiDataset:
        """Load the wiki described by a JSON file."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProtocolError(f"could not read wiki dataset {path}: {error}") from error
        if not isinstance(raw, dict):
            raise ProtocolError(f"{path} must contain an object")
        return WikiDataset(
            spaces=[self._space(entry) for entry in self._sequence(raw, "spaces")],
            pages=[self._page_record(entry) for entry in self._sequence(raw, "pages")],
        )

    def _space(self, entry: JsonObject) -> SpaceRecord:
        """Build one space record."""
        space = wire.Space(
            key=self._text(entry, "key"),
            name=self._text(entry, "name"),
            is_personal=bool(entry.get("is_personal", False)),
            homepage_id=self._optional(entry, "homepage_id"),
        )
        return SpaceRecord(space, readable_by=frozenset(self._strings(entry, "readable_by")))

    def _page_record(self, entry: JsonObject) -> PageRecord:
        """Build one page record, with its discussion and history."""
        page = self._page(entry)
        comments = tuple(self._comment(item, page.page_id) for item in self._sequence(entry, "comments"))
        return PageRecord(
            page,
            comments=comments,
            history=self._history(entry, page),
            restricted_to=frozenset(self._strings(entry, "restricted_to")),
        )

    def _page(self, entry: JsonObject) -> wire.Page:
        """Build one page payload."""
        created_at = self._text(entry, "created_at")
        return wire.Page(
            page_id=self._text(entry, "page_id"),
            space_key=self._text(entry, "space_key"),
            title=self._text(entry, "title"),
            body=self._text(entry, "body"),
            body_format=wire.ContentFormat(str(entry.get("body_format", wire.ContentFormat.MARKDOWN.value))),
            status=wire.PageStatus(str(entry.get("status", wire.PageStatus.CURRENT.value))),
            parent_id=self._optional(entry, "parent_id"),
            labels=self._strings(entry, "labels"),
            created_at=self._moment(created_at),
            created_by=self._author(entry.get("created_by")),
            last_modified_at=self._moment(str(entry.get("last_modified_at", created_at))),
            last_modified_by=self._author(entry.get("last_modified_by")),
            version=int(entry.get("version", 1)),
            url=str(entry.get("url", "")),
        )

    def _comment(self, entry: JsonObject, page_id: str) -> wire.Comment:
        """Build one comment payload."""
        return wire.Comment(
            comment_id=self._text(entry, "comment_id"),
            page_id=page_id,
            body=self._text(entry, "body"),
            author=self._author(entry.get("author")),
            created_at=self._moment(self._text(entry, "created_at")),
            parent_comment_id=self._optional(entry, "parent_comment_id"),
            is_resolved=bool(entry.get("is_resolved", False)),
        )

    def _history(self, entry: JsonObject, page: wire.Page) -> wire.PageHistory:
        """Build a page's history, synthesising one when the dataset omits it."""
        declared = self._sequence(entry, "versions")
        if not declared:
            return wire.PageHistory(
                page_id=page.page_id,
                versions=(
                    wire.PageVersion(
                        version=page.version,
                        modified_at=page.last_modified_at,
                        modified_by=page.last_modified_by,
                    ),
                ),
            )
        versions = [self._version(item) for item in declared]
        return wire.PageHistory(
            page_id=page.page_id,
            versions=tuple(sorted(versions, key=lambda item: item.version, reverse=True)),
        )

    def _version(self, entry: JsonObject) -> wire.PageVersion:
        """Build one history entry."""
        return wire.PageVersion(
            version=int(entry.get("version", 1)),
            modified_at=self._moment(self._text(entry, "modified_at")),
            modified_by=self._author(entry.get("modified_by")),
            message=self._optional(entry, "message"),
            is_minor_edit=bool(entry.get("is_minor_edit", False)),
        )

    def _author(self, entry: Any) -> wire.Author | None:
        """Build an author, tolerating one the dataset does not name."""
        if entry is None:
            return None
        if not isinstance(entry, Mapping):
            raise ProtocolError("an author must be an object")
        return wire.Author(
            account_id=self._text(entry, "account_id"),
            display_name=self._optional(entry, "display_name"),
        )

    @staticmethod
    def _text(entry: JsonObject, key: str) -> str:
        """Return a mandatory string field."""
        value = entry.get(key)
        if not isinstance(value, str):
            raise ProtocolError(f"field {key!r} must be a string")
        return value

    @staticmethod
    def _optional(entry: JsonObject, key: str) -> str | None:
        """Return an optional string field."""
        value = entry.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ProtocolError(f"field {key!r} must be a string when present")
        return value

    @staticmethod
    def _strings(entry: JsonObject, key: str) -> tuple[str, ...]:
        """Return an optional list of strings."""
        value = entry.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ProtocolError(f"field {key!r} must be a list of strings")
        return tuple(value)

    @staticmethod
    def _sequence(entry: JsonObject, key: str) -> Sequence[Any]:
        """Return an optional list field, defaulting to an empty one."""
        value = entry.get(key, [])
        if not isinstance(value, list):
            raise ProtocolError(f"field {key!r} must be a list")
        return value

    @staticmethod
    def _moment(value: str) -> datetime:
        """Parse an ISO-8601 timestamp."""
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ProtocolError(f"invalid timestamp {value!r}") from error
