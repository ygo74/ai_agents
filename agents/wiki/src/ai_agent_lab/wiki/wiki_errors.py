"""Errors crossing the wiki MCP boundary.

Transport and protocol failures never leak upwards. The MCP client translates
them into these domain-meaningful exceptions so that skills and the application
reason about wiki concepts, not about HTTP status codes or JSON-RPC frames.

``WikiAccessDeniedError`` carries more weight here than its mail equivalent. A
wiki has per-space and per-page restrictions, so a refusal is a normal, frequent
answer rather than an incident: the person asking simply may not read that page.
It must stay distinguishable from "no such page", because collapsing the two
would let an agent report a restricted page as non-existent - or worse, let a
caller infer which restricted pages exist.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from ai_agent_lab.core.errors import DomainError


class WikiToolError(DomainError):
    """Base class for every failure of a wiki MCP tool."""


class WikiErrorCode(StrEnum):
    """Stable code a wiki MCP server prefixes its failures with.

    A failure crossing the MCP boundary arrives as text. Without an agreed code
    the client can only guess, and a page that does not exist would be
    indistinguishable from a page the caller may not read. The code keeps the
    distinction, and is part of the contract a server implements.
    """

    NOT_FOUND = "wiki_not_found"
    ACCESS_DENIED = "wiki_access_denied"
    CONFLICT = "wiki_conflict"
    UNAVAILABLE = "wiki_unavailable"
    PROTOCOL = "wiki_protocol"


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


_SEPARATOR = ": "


def code_of(error: WikiToolError) -> WikiErrorCode:
    """Return the code a server should report a failure under."""
    if isinstance(error, WikiNotFoundError):
        return WikiErrorCode.NOT_FOUND
    if isinstance(error, WikiAccessDeniedError):
        return WikiErrorCode.ACCESS_DENIED
    if isinstance(error, WikiConcurrentEditError):
        return WikiErrorCode.CONFLICT
    if isinstance(error, WikiToolUnavailableError):
        return WikiErrorCode.UNAVAILABLE
    return WikiErrorCode.PROTOCOL


def encode_failure(error: WikiToolError) -> str:
    """Render a failure as the coded text a client can decode."""
    return f"{code_of(error).value}{_SEPARATOR}{error}"


def decode_failure(reported: str) -> WikiToolError:
    """Rebuild the failure a server reported.

    The code is searched for rather than expected at the start: a server is free
    to prefix its own context, and the MCP runtime does exactly that. The
    earliest code wins, so the outcome never depends on dictionary order.

    A server that does not speak our codes still fails loudly: its text is kept
    and reported as a protocol error rather than guessed at.
    """
    found = _first_code(reported)
    if found is None:
        return WikiToolProtocolError(reported)
    code, index = found
    detail = reported[index + len(code) + len(_SEPARATOR) :].strip()
    return _FAILURES[code](detail or reported)


def _first_code(reported: str) -> tuple[str, int] | None:
    """Return the earliest known code in a reported failure, if any."""
    positions = [
        (index, code) for code in _FAILURES if (index := reported.find(f"{code}{_SEPARATOR}")) >= 0
    ]
    if not positions:
        return None
    index, code = min(positions)
    return code, index


_FAILURES: dict[str, Callable[[str], WikiToolError]] = {
    WikiErrorCode.NOT_FOUND.value: lambda detail: WikiNotFoundError(message=detail),
    WikiErrorCode.ACCESS_DENIED.value: lambda detail: WikiAccessDeniedError(message=detail),
    WikiErrorCode.CONFLICT.value: lambda detail: WikiConcurrentEditError(message=detail),
    WikiErrorCode.UNAVAILABLE.value: WikiToolUnavailableError,
    WikiErrorCode.PROTOCOL.value: WikiToolProtocolError,
}
