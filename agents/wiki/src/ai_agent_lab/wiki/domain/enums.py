"""Enumerations of the wiki domain."""

from __future__ import annotations

from enum import StrEnum


class WikiContentFormat(StrEnum):
    """How the body of a page is represented.

    A wiki stores its pages in a markup of its own - Confluence storage format is
    XHTML, others use wiki markup. A dialect normalises what it receives into one
    of these, so nothing above the MCP boundary parses vendor markup.

    ``PLAIN_TEXT`` is the honest answer when a server returned prose with no
    recoverable structure. Saying so is better than claiming Markdown and letting
    a caller trust headings that are not there.
    """

    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"


class WikiSortOrder(StrEnum):
    """Ordering applied to search results."""

    RELEVANCE = "relevance"
    LAST_MODIFIED = "last_modified"
    CREATED = "created"
    TITLE = "title"


class WikiPageStatus(StrEnum):
    """Publication state of a page.

    Archived and draft pages exist and are searchable, but answering a question
    from one without saying so would be misleading, so the state travels with the
    page rather than being filtered away silently.
    """

    CURRENT = "current"
    DRAFT = "draft"
    ARCHIVED = "archived"


class WikiFreshness(StrEnum):
    """How current a page is judged to be.

    Assigned deterministically from the last modification date, never by a
    language model.
    """

    FRESH = "fresh"
    AGEING = "ageing"
    STALE = "stale"
