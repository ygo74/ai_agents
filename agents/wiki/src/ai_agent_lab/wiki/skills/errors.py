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
