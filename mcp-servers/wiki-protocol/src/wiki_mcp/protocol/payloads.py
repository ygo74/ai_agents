"""Shapes carried on the wire.

Plain JSON types only: text, numbers, booleans and timestamps. No domain model,
no untrusted-content wrapper, no security metadata. A server fills these in; a
caller decides what they mean.

Free text stays plain text here on purpose. Treating it as untrusted is the
caller's responsibility, and a server has no way of knowing what a caller will do
with it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContentFormat(StrEnum):
    """How the body of a page is represented on the wire."""

    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"


class PageStatus(StrEnum):
    """Publication state of a page."""

    CURRENT = "current"
    DRAFT = "draft"
    ARCHIVED = "archived"


class SortOrder(StrEnum):
    """Ordering applied to search results."""

    RELEVANCE = "relevance"
    LAST_MODIFIED = "last_modified"
    CREATED = "created"
    TITLE = "title"


class Payload(BaseModel):
    """Base class for the shapes crossing the boundary.

    Unknown fields are ignored rather than refused, so a server may add one
    without breaking every caller at once.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")


class Author(Payload):
    """Somebody who wrote or edited something."""

    account_id: str
    display_name: str | None = None


class Space(Payload):
    """A named area grouping related pages."""

    key: str
    name: str
    is_personal: bool = False
    homepage_id: str | None = None


class PageReference(Payload):
    """A search hit. Never carries a whole body."""

    page_id: str
    space_key: str
    title: str
    excerpt: str | None = None
    status: PageStatus = PageStatus.CURRENT
    last_modified_at: datetime
    version: int = Field(ge=1)
    url: str = ""


class Page(Payload):
    """A complete page."""

    page_id: str
    space_key: str
    title: str
    body: str
    body_format: ContentFormat = ContentFormat.MARKDOWN
    status: PageStatus = PageStatus.CURRENT
    parent_id: str | None = None
    labels: tuple[str, ...] = ()
    created_at: datetime
    created_by: Author | None = None
    last_modified_at: datetime
    last_modified_by: Author | None = None
    version: int = Field(ge=1)
    url: str = ""


class Comment(Payload):
    """A comment attached to a page."""

    comment_id: str
    page_id: str
    body: str
    body_format: ContentFormat = ContentFormat.MARKDOWN
    author: Author | None = None
    created_at: datetime
    parent_comment_id: str | None = None
    is_resolved: bool = False


class PageVersion(Payload):
    """One entry of a page's revision history."""

    version: int = Field(ge=1)
    modified_at: datetime
    modified_by: Author | None = None
    message: str | None = None
    is_minor_edit: bool = False


class PageHistory(Payload):
    """The revision history of one page, most recent first."""

    page_id: str
    versions: tuple[PageVersion, ...] = ()


class PageTree(Payload):
    """The direct children of one page."""

    parent_id: str
    children: tuple[PageReference, ...] = ()


class SearchResult(Payload):
    """The outcome of a search.

    ``truncated`` says the wiki holds more matches than were returned, so a
    caller can tell "there are three pages" from "here are the first three".
    """

    references: tuple[PageReference, ...] = ()
    total_count: int = Field(ge=0)
    truncated: bool = False


class SpaceList(Payload):
    """The spaces a caller may read.

    A list is wrapped in an object rather than returned bare so a server can add
    a field later without changing the shape of every response.
    """

    spaces: tuple[Space, ...] = ()


class CommentList(Payload):
    """The comments attached to a page."""

    comments: tuple[Comment, ...] = ()
