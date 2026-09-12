"""Errors of the wiki domain."""

from __future__ import annotations

from ai_agent_lab.core.errors import DomainError


class WikiDomainError(DomainError):
    """Base class for errors of the wiki domain."""


class WikiSpaceUnknownError(WikiDomainError):
    """Raised when a request names a space the wiki does not expose."""

    def __init__(self, space_key: str) -> None:
        super().__init__(f"no space is available under key {space_key!r}")
        self.space_key = space_key


class EmptySearchRequestError(WikiDomainError):
    """Raised when a search would constrain nothing at all.

    A wiki search with no query, no space, no label and no date window asks for
    the entire wiki. Answering it would return an arbitrary page of results that
    look like an answer, so it is refused instead.
    """

    def __init__(self) -> None:
        super().__init__("a wiki search must constrain at least one of text, space, label or date")


class UngroundedAnswerError(WikiDomainError):
    """Raised when an answer was requested with no source page to ground it in.

    The wiki agent answers *from the documentation*. With nothing retrieved there
    is nothing to answer from, and producing prose anyway would be the exact
    failure mode this agent exists to avoid.
    """

    def __init__(self, question: str) -> None:
        super().__init__("no wiki page was retrieved, so the question cannot be answered from documentation")
        self.question = question


class WikiDraftNotFoundError(WikiDomainError):
    """Raised when a draft reference names nothing this user prepared.

    Also raised when the reference belongs to somebody else. The two cases are
    reported identically on purpose: telling a caller that a reference exists but
    is not theirs would confirm what another person is drafting.
    """

    def __init__(self, reference: str) -> None:
        super().__init__(f"no page draft is held under the reference {reference!r}")
        self.reference = reference

