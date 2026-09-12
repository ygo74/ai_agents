"""Typed models of the wiki domain.

These models are the vocabulary shared by skills, MCP contracts and framework
adapters. They carry no infrastructure knowledge: nothing here is aware of
Confluence, of storage format, of CQL, of REST or of any agent framework.

Text produced by third parties - page titles, bodies, excerpts, space names,
comments, author display names, labels, version messages - is wrapped in
:class:`~ai_agent_lab.core.security.untrusted.UntrustedText` so that it can never
be silently treated as an instruction. On a wiki this matters more than it does
on a mailbox: a page is durable, edited by many people, often reachable by
externals, and a payload planted in it is read by every future question.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_agent_lab.core.security.untrusted import UntrustedText
from ai_agent_lab.wiki.domain.enums import (
    WikiContentFormat,
    WikiFreshness,
    WikiPageStatus,
    WikiSortOrder,
)

MAX_SEARCH_LIMIT = 50
DEFAULT_SEARCH_LIMIT = 10
MAX_PAGE_DEPTH = 10


class DomainModel(BaseModel):
    """Base class for immutable, strictly validated domain models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_timezone(value: datetime) -> datetime:
    """Normalise a datetime to UTC and reject naive values."""
    if value.tzinfo is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


class WikiAuthor(DomainModel):
    """A person who wrote or edited something.

    ``account_id`` is the stable identifier the source system assigns. The
    display name is chosen by the person and is therefore untrusted.
    """

    account_id: str = Field(min_length=1)
    display_name: UntrustedText | None = None


class WikiSpace(DomainModel):
    """A named area grouping related pages.

    ``key`` is the short, stable handle a wiki gives a space. It is trusted
    because the system generates and validates it; the human-facing name is not.
    """

    key: str = Field(min_length=1)
    name: UntrustedText
    is_personal: bool = False
    homepage_id: str | None = None


class WikiPageReference(DomainModel):
    """Lightweight pointer to a page, as returned by a search.

    A search returns references rather than whole pages, for the same reason a
    mailbox search returns headers: a broad query would otherwise pull every body
    into the context window. A wiki page is routinely far longer than an email,
    so the consequence is worse here.

    ``excerpt`` is whatever fragment the source system chose to show. It is a
    piece of the page and is untrusted exactly like the page.
    """

    page_id: str = Field(min_length=1)
    space_key: str = Field(min_length=1)
    title: UntrustedText
    excerpt: UntrustedText | None = None
    status: WikiPageStatus = WikiPageStatus.CURRENT
    last_modified_at: datetime
    version: int = Field(ge=1)
    url: str = ""

    _normalise_last_modified_at = field_validator("last_modified_at")(_require_timezone)


class WikiPage(DomainModel):
    """A complete page, body included."""

    page_id: str = Field(min_length=1)
    space_key: str = Field(min_length=1)
    title: UntrustedText
    body: UntrustedText
    body_format: WikiContentFormat = WikiContentFormat.MARKDOWN
    status: WikiPageStatus = WikiPageStatus.CURRENT
    parent_id: str | None = None
    labels: tuple[UntrustedText, ...] = ()
    created_at: datetime
    created_by: WikiAuthor | None = None
    last_modified_at: datetime
    last_modified_by: WikiAuthor | None = None
    version: int = Field(ge=1)
    url: str = ""

    _normalise_created_at = field_validator("created_at")(_require_timezone)
    _normalise_last_modified_at = field_validator("last_modified_at")(_require_timezone)

    @model_validator(mode="after")
    def _validate_chronology(self) -> WikiPage:
        """Refuse a page modified before it existed.

        A dialect that mapped the wrong field would otherwise produce a page that
        silently breaks every freshness calculation downstream.
        """
        if self.last_modified_at < self.created_at:
            raise ValueError(f"page {self.page_id!r} was modified before it was created")
        return self

    @model_validator(mode="after")
    def _validate_parentage(self) -> WikiPage:
        """Refuse a page that is its own parent."""
        if self.parent_id is not None and self.parent_id == self.page_id:
            raise ValueError(f"page {self.page_id!r} cannot be its own parent")
        return self

    def to_reference(self) -> WikiPageReference:
        """Project the page onto its lightweight pointer."""
        return WikiPageReference(
            page_id=self.page_id,
            space_key=self.space_key,
            title=self.title,
            status=self.status,
            last_modified_at=self.last_modified_at,
            version=self.version,
            url=self.url,
        )


class WikiComment(DomainModel):
    """A comment attached to a page.

    ``parent_comment_id`` carries a reply, so a discussion keeps its shape
    instead of being flattened into an undated list.
    """

    comment_id: str = Field(min_length=1)
    page_id: str = Field(min_length=1)
    body: UntrustedText
    body_format: WikiContentFormat = WikiContentFormat.MARKDOWN
    author: WikiAuthor | None = None
    created_at: datetime
    parent_comment_id: str | None = None
    is_resolved: bool = False

    _normalise_created_at = field_validator("created_at")(_require_timezone)

    @model_validator(mode="after")
    def _validate_parentage(self) -> WikiComment:
        """Refuse a comment that replies to itself."""
        if self.parent_comment_id is not None and self.parent_comment_id == self.comment_id:
            raise ValueError(f"comment {self.comment_id!r} cannot reply to itself")
        return self


class WikiPageVersion(DomainModel):
    """One entry of a page's revision history.

    ``message`` is the note the editor typed, so it is untrusted like any other
    third-party text.
    """

    version: int = Field(ge=1)
    modified_at: datetime
    modified_by: WikiAuthor | None = None
    message: UntrustedText | None = None
    is_minor_edit: bool = False

    _normalise_modified_at = field_validator("modified_at")(_require_timezone)


class WikiPageHistory(DomainModel):
    """The revision history of one page, most recent first."""

    page_id: str = Field(min_length=1)
    versions: tuple[WikiPageVersion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_ordering(self) -> WikiPageHistory:
        """Refuse a history that is not ordered from newest to oldest.

        Callers read ``versions[0]`` as the current revision. Accepting either
        order would make that read correct half the time.
        """
        numbers = [entry.version for entry in self.versions]
        if numbers != sorted(numbers, reverse=True):
            raise ValueError(f"history of page {self.page_id!r} must run from newest to oldest")
        if len(set(numbers)) != len(numbers):
            raise ValueError(f"history of page {self.page_id!r} repeats a version number")
        return self

    @property
    def current(self) -> WikiPageVersion:
        """The most recent revision."""
        return self.versions[0]


class WikiPageTree(DomainModel):
    """The direct children of one page, in the order the wiki presents them.

    Only one level: an agent that needs a whole subtree asks again. Returning an
    unbounded tree in a single call is how a well-meaning question about a small
    space consumes a context window.
    """

    parent_id: str = Field(min_length=1)
    children: tuple[WikiPageReference, ...] = ()


class WikiSearchRequest(DomainModel):
    """A structured wiki query.

    One request type covers every search variation, so the tool surface does not
    grow a tool per filter. Free text is optional: listing the recently changed
    pages of a space is a legitimate search with no query at all.
    """

    text: str = ""
    space_keys: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    title_contains: str = ""
    modified_after: datetime | None = None
    modified_before: datetime | None = None
    statuses: tuple[WikiPageStatus, ...] = (WikiPageStatus.CURRENT,)
    sort_order: WikiSortOrder = WikiSortOrder.RELEVANCE
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)

    _normalise_modified_after = field_validator("modified_after")(
        lambda value: None if value is None else _require_timezone(value)
    )
    _normalise_modified_before = field_validator("modified_before")(
        lambda value: None if value is None else _require_timezone(value)
    )

    @model_validator(mode="after")
    def _validate_window(self) -> WikiSearchRequest:
        """Refuse a time window that can never match."""
        if self.modified_after is None or self.modified_before is None:
            return self
        if self.modified_after > self.modified_before:
            raise ValueError("modified_after must not be later than modified_before")
        return self

    @property
    def is_empty(self) -> bool:
        """Whether the request constrains nothing at all."""
        return not any(
            (
                self.text.strip(),
                self.space_keys,
                self.labels,
                self.title_contains.strip(),
                self.modified_after,
                self.modified_before,
            )
        )


class WikiSearchResult(DomainModel):
    """The outcome of a wiki search.

    ``truncated`` says the wiki holds more matches than were returned, so a
    caller can tell "there are three pages" from "here are the first three".
    """

    references: tuple[WikiPageReference, ...] = ()
    total_count: int = Field(ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def _validate_count(self) -> WikiSearchResult:
        """Refuse a total smaller than what was actually returned."""
        if self.total_count < len(self.references):
            raise ValueError("total_count cannot be smaller than the number of returned references")
        return self


class WikiSourceReference(DomainModel):
    """A page an analysis was grounded in.

    Identifiers and a version, never text. A citation exists so a person can go
    and read the page themselves, and carrying the title here would put
    third-party text into something presented as a fact about provenance.
    """

    page_id: str = Field(min_length=1)
    space_key: str = Field(min_length=1)
    version: int = Field(ge=1)
    url: str = ""


class WikiPageSummary(DomainModel):
    """A structured summary of one or several pages."""

    summary: str
    key_points: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    sources: tuple[WikiSourceReference, ...] = ()


class WikiAnswer(DomainModel):
    """An answer grounded in documentation.

    The three parts are kept apart deliberately. ``answer`` is what the
    documentation says; ``uncertainties`` is what it does not settle; and
    ``is_grounded`` is false when the retrieved pages did not actually contain
    the answer. Merging them would let a confident paragraph hide the fact that
    nothing supported it.
    """

    question: str
    answer: str
    is_grounded: bool = True
    uncertainties: tuple[str, ...] = ()
    sources: tuple[WikiSourceReference, ...] = ()


class WikiPageFreshness(DomainModel):
    """How current one page is judged to be.

    Assigned from the last modification date by a deterministic rule, never by a
    language model: an arithmetic comparison of two dates has one right answer.
    """

    page_id: str = Field(min_length=1)
    title: UntrustedText
    freshness: WikiFreshness
    days_since_change: int = Field(ge=0)
    last_modified_at: datetime
    version: int = Field(ge=1)

    _normalise_last_modified_at = field_validator("last_modified_at")(_require_timezone)


class WikiFreshnessReport(DomainModel):
    """The freshness of a set of pages, most stale first."""

    pages: tuple[WikiPageFreshness, ...] = ()
    assessed_at: datetime

    _normalise_assessed_at = field_validator("assessed_at")(_require_timezone)

    @property
    def stale(self) -> tuple[WikiPageFreshness, ...]:
        """The pages judged stale."""
        return tuple(page for page in self.pages if page.freshness is WikiFreshness.STALE)


class WikiPageDraft(DomainModel):
    """Page content prepared but not yet written to the wiki.

    Composing and writing are two separate turns, and the draft is what joins
    them. The title and body are produced by reasoning over pages other people
    wrote, so they stay untrusted until a human has approved them.

    ``page_id`` distinguishes the two things a draft can become. Absent, the
    draft creates a page in ``space_key``. Present, it replaces the body of that
    page, and ``expected_version`` carries the revision it was composed against.

    Refusing a draft that is neither is not pedantry: a draft with no space and
    no page has no destination, and discovering that at write time would mean
    discovering it after the user had already approved something.
    """

    space_key: str = ""
    title: UntrustedText | None = None
    body: UntrustedText
    page_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    parent_id: str | None = None

    @property
    def replaces_a_page(self) -> bool:
        """Whether writing this draft overwrites an existing page."""
        return self.page_id is not None

    @model_validator(mode="after")
    def _validate_destination(self) -> WikiPageDraft:
        """Refuse a draft that names nowhere to go."""
        if self.page_id is None and not self.space_key:
            raise ValueError("a page draft must name either the page it replaces or the space it is created in")
        if self.page_id is None and self.title is None:
            raise ValueError("a page draft that creates a page must carry a title")
        return self

    @model_validator(mode="after")
    def _validate_parentage(self) -> WikiPageDraft:
        """Refuse a draft parented to the very page it replaces."""
        if self.parent_id is not None and self.parent_id == self.page_id:
            raise ValueError("a page draft cannot be its own parent")
        return self

