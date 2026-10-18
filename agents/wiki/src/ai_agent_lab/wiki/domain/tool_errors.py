"""Application-facing errors for Wiki operations."""

from __future__ import annotations

from ai_agent_lab.wiki.domain.errors import WikiDomainError


class WikiToolError(WikiDomainError):
    """Base class for every failure of a wiki MCP tool."""


class WikiNotFoundError(WikiToolError):
    """Raised when the requested page, space or comment does not exist."""

    def __init__(self, resource: str = "", identifier: str = "", *, message: str = "") -> None:
        super().__init__(message or f"{resource} {identifier!r} was not found")
        self.resource = resource
        self.identifier = identifier


class WikiAccessDeniedError(WikiToolError):
    """Raised when the source system refuses access for the calling user.

    The wiki remains the authority on authorisation; this error carries its
    refusal without reinterpreting it. It is never converted into an empty
    result: an agent that silently swallowed a refusal would tell the user the
    documentation says nothing, when in fact they are not allowed to see it.
    """

    def __init__(self, identifier: str = "", *, message: str = "") -> None:
        super().__init__(message or f"access to {identifier!r} was denied by the wiki")
        self.identifier = identifier


class WikiToolUnavailableError(WikiToolError):
    """Raised when the wiki MCP server is unreachable or timed out."""


class WikiConcurrentEditError(WikiToolError):
    """Raised when a page moved on between reading it and writing it back.

    A wiki is edited by many people at once. An agent that read version 4,
    reasoned about it, and wrote version 5 would silently discard whatever a
    colleague committed in the meantime - and the person who lost their work
    would have no way of knowing an agent did it.

    Refusing is the only safe answer: the caller re-reads and decides again.
    """

    def __init__(
        self,
        page_id: str = "",
        expected_version: int | None = None,
        actual_version: int | None = None,
        *,
        message: str = "",
    ) -> None:
        super().__init__(
            message
            or (
                f"page {page_id!r} is at version {actual_version}, not the expected "
                f"{expected_version}: somebody edited it in the meantime"
            )
        )
        self.page_id = page_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class WikiToolProtocolError(WikiToolError):
    """Raised when the wiki MCP server returned a payload the domain rejects.

    An unexpected payload is an error, never a silently accepted partial result.
    """
