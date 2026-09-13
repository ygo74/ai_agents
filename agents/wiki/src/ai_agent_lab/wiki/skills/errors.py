"""Errors raised by the wiki skills."""

from __future__ import annotations

from ai_agent_lab.core.errors import DomainError


class WikiSkillError(DomainError):
    """Base class for failures of a wiki skill."""


class EmptyPageSelectionError(WikiSkillError):
    """Raised when a skill was asked to work on no page at all."""

    def __init__(self, skill: str) -> None:
        super().__init__(f"{skill} was given no page to work on")
        self.skill = skill


class UngroundedWikiResultError(WikiSkillError):
    """Raised when a model cited a page that was not in the analysed context.

    This is the defence that matters most on a wiki. Page content is written by
    third parties, and a planted instruction asking the model to attribute a
    claim to a page nobody retrieved would otherwise reach the user as a sourced
    fact. A citation that cannot be traced back to something actually read is
    refused rather than shown.
    """

    def __init__(self, page_id: str) -> None:
        super().__init__(f"the model cited page {page_id!r}, which was not among the retrieved pages")
        self.page_id = page_id


class EmptyPageContentError(WikiSkillError):
    """Raised when a page would be written with no content at all.

    An empty page is not a harmless no-op: it appears in the space, is
    attributed to the user, notifies everyone watching, and replaces whatever a
    colleague had written if it lands on an existing page.
    """

    def __init__(self, skill: str) -> None:
        super().__init__(f"{skill} was asked to write a page with an empty body")
        self.skill = skill


class EmptyCommentError(WikiSkillError):
    """Raised when a comment would be posted with no text."""

    def __init__(self) -> None:
        super().__init__("a comment cannot be posted with an empty body")

