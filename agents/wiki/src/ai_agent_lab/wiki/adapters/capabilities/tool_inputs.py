"""Argument schemas of the capabilities offered to the model.

These are contracts, so they live in code rather than in a delivered file. A
model fills them in; the descriptions are what it reads to know how.

Limits are declared here rather than checked later. A model asked for "all the
pages" will happily pass a limit of a thousand, and the honest answer is that the
schema does not accept one.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_lab.wiki.domain.enums import WikiPageStatus, WikiSortOrder
from ai_agent_lab.wiki.domain.models import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT

MAX_SELECTED_PAGES = 10


class ToolInput(BaseModel):
    """Base class for the arguments a model supplies."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NoInput(ToolInput):
    """Arguments of a capability that takes none."""


class PageInput(ToolInput):
    """One page, by identifier."""

    page_id: str = Field(min_length=1, description="Identifier of the page, as returned by a search.")


class PagesInput(ToolInput):
    """Several pages, by identifier."""

    page_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_SELECTED_PAGES,
        description="Identifiers of the pages to work on, as returned by a search.",
    )


class SummarisePageInput(ToolInput):
    """One page, and how much of its surroundings to read."""

    page_id: str = Field(min_length=1, description="Identifier of the page to summarise.")
    include_comments: bool = Field(
        default=False,
        description=(
            "Also read the comments on the page. Comments often carry decisions or objections "
            "that never made it into the body."
        ),
    )
    include_children: bool = Field(
        default=False,
        description=(
            "Also read the direct children of the page, one level down. Use this to summarise a "
            "small section of a space rather than a single page."
        ),
    )


class SearchWikiInput(ToolInput):
    """A structured wiki query.

    At least one constraint is required. A search constraining nothing asks for
    the whole wiki, and would be answered with an arbitrary page of results that
    look exactly like an answer.
    """

    text: str = Field(default="", description="Free-text keywords to look for in titles and bodies.")
    space_keys: tuple[str, ...] = Field(
        default=(),
        description="Restrict to these spaces, by key. Use list_spaces to discover the keys.",
    )
    labels: tuple[str, ...] = Field(
        default=(),
        description="Restrict to pages carrying all of these labels.",
    )
    title_contains: str = Field(default="", description="Restrict to titles containing this fragment.")
    modified_after: str | None = Field(
        default=None,
        description="ISO-8601 date or date-time. Restrict to pages changed on or after it.",
    )
    modified_before: str | None = Field(
        default=None,
        description="ISO-8601 date or date-time. Restrict to pages changed on or before it.",
    )
    statuses: tuple[WikiPageStatus, ...] = Field(
        default=(WikiPageStatus.CURRENT,),
        description="Publication states to include. Archived pages are excluded by default.",
    )
    sort_order: WikiSortOrder = Field(
        default=WikiSortOrder.RELEVANCE,
        description="How to order the results.",
    )
    limit: int = Field(
        default=DEFAULT_SEARCH_LIMIT,
        ge=1,
        le=MAX_SEARCH_LIMIT,
        description="Maximum number of pages to return. Narrow the query rather than raising this.",
    )


class AnswerFromWikiInput(ToolInput):
    """A question, and where to look for the answer."""

    question: str = Field(
        min_length=1,
        description="The question to answer, in the words the person used.",
    )
    space_keys: tuple[str, ...] = Field(
        default=(),
        description="Restrict the search to these spaces, by key. Leave empty to search everywhere.",
    )


class AssessFreshnessInput(ToolInput):
    """Which pages to judge the freshness of.

    Either explicit identifiers or a space. A request naming neither would have
    to assess the whole wiki, which is a different and much more expensive
    question than the one this capability answers.
    """

    page_ids: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_SELECTED_PAGES,
        description="Identifiers of the pages to assess. Leave empty to assess a whole space.",
    )
    space_key: str = Field(
        default="",
        description="Assess every readable page of this space instead of named pages.",
    )

    @model_validator(mode="after")
    def _require_a_subject(self) -> AssessFreshnessInput:
        """Refuse a request that names neither pages nor a space."""
        if not self.page_ids and not self.space_key.strip():
            raise ValueError("name either page_ids or a space_key: assessing the whole wiki is not offered")
        return self


class DraftPageContentInput(ToolInput):
    """What to write, and where it is eventually meant to go.

    One schema for both destinations, because the choice between them is a
    single fact: ``page_id`` names the page to revise, and its absence means a
    new page in ``space_key``. Two schemas would let a model supply both and
    leave the capability to guess which was meant.
    """

    instruction: str = Field(
        min_length=1,
        description="What the page should say, in the words the person used.",
    )
    page_id: str = Field(
        default="",
        description=(
            "Identifier of an existing page to revise. Leave empty to compose a new page, and "
            "then supply space_key and title instead."
        ),
    )
    space_key: str = Field(
        default="",
        description="Key of the space a new page would be created in. Required unless page_id is given.",
    )
    title: str = Field(
        default="",
        description="Title of a new page. Required unless page_id is given.",
    )
    source_page_ids: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_SELECTED_PAGES,
        description="Existing pages to use as reference material when composing a new page.",
    )
    parent_id: str = Field(
        default="",
        description="Identifier of the page a new page should hang under, if any.",
    )

    @model_validator(mode="after")
    def _require_a_destination(self) -> DraftPageContentInput:
        """Refuse a request that says neither which page nor which space."""
        if self.page_id.strip():
            return self
        if not self.space_key.strip() or not self.title.strip():
            raise ValueError(
                "supply page_id to revise an existing page, or both space_key and title to compose a new one"
            )
        return self


class PageDraftInput(ToolInput):
    """The draft a write capability should publish."""

    draft_reference: str = Field(
        min_length=1,
        description="Reference returned by draft_page_content. The content written is exactly that draft.",
    )


class AddCommentInput(ToolInput):
    """A comment to post on a page."""

    page_id: str = Field(min_length=1, description="Identifier of the page to comment on.")
    body: str = Field(min_length=1, description="Text of the comment, as it will appear.")
    parent_comment_id: str = Field(
        default="",
        description="Identifier of the comment this replies to, if it is a reply.",
    )

