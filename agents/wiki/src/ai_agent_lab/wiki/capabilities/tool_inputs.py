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
