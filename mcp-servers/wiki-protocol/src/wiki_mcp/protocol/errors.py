"""How a failure is reported on the wire.

MCP reports a failure as text. Without an agreed code, a caller could not tell a
page that does not exist from a page it may not read, and would be left guessing
from prose written for a human.

On a wiki that distinction is not academic. Pages and spaces are restricted per
person, so "you may not read this" is a routine answer. Collapsing it into "no
such page" would have an agent telling users the documentation does not exist.

A server prefixes its message with a code; a caller reads the code back. Both
sides tolerate extra text around it, because runtimes wrap error messages.
"""

from __future__ import annotations

from enum import StrEnum

SEPARATOR = ": "


class WikiErrorCode(StrEnum):
    """Stable code a wiki MCP server reports a failure under."""

    NOT_FOUND = "wiki_not_found"
    ACCESS_DENIED = "wiki_access_denied"
    CONFLICT = "wiki_conflict"
    UNAVAILABLE = "wiki_unavailable"
    PROTOCOL = "wiki_protocol"


def encode(code: WikiErrorCode, detail: str) -> str:
    """Render a failure as the coded text a caller can decode."""
    return f"{code.value}{SEPARATOR}{detail}"


def decode(reported: str) -> tuple[WikiErrorCode, str]:
    """Read the code and detail out of a reported failure.

    The code is searched for rather than expected at the start: a server may
    prefix its own context, and MCP runtimes do exactly that. The earliest code
    wins, so the outcome never depends on declaration order.

    Text carrying no known code is reported as a protocol failure rather than
    guessed at.
    """
    found = _first_code(reported)
    if found is None:
        return WikiErrorCode.PROTOCOL, reported
    code, index = found
    detail = reported[index + len(code.value) + len(SEPARATOR) :].strip()
    return code, detail or reported


class WikiServerError(Exception):
    """Base class for a failure a wiki server reports to its caller.

    The exception types live with the codes so that every server reports the
    same five failures, and a caller only ever has five cases to handle.
    """

    code = WikiErrorCode.PROTOCOL

    def reported(self) -> str:
        """Render the failure as the coded text the protocol defines."""
        return encode(self.code, str(self))


class NotFoundError(WikiServerError):
    """Raised when the requested page, space or comment does not exist."""

    code = WikiErrorCode.NOT_FOUND

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} {identifier!r} was not found")


class AccessDeniedError(WikiServerError):
    """Raised when the wiki refuses the access for the calling user."""

    code = WikiErrorCode.ACCESS_DENIED


class ConflictError(WikiServerError):
    """Raised when a page moved on between reading it and writing it back.

    A wiki is edited by many people at once. Reporting this rather than applying
    the write is what keeps an agent from silently discarding a colleague's edit.
    """

    code = WikiErrorCode.CONFLICT


class UnavailableError(WikiServerError):
    """Raised when the wiki cannot be reached."""

    code = WikiErrorCode.UNAVAILABLE


class ProtocolError(WikiServerError):
    """Raised when the wiki answered something unusable."""

    code = WikiErrorCode.PROTOCOL


def _first_code(reported: str) -> tuple[WikiErrorCode, int] | None:
    """Return the earliest known code in a reported failure, if any."""
    positions = [
        (index, code)
        for code in WikiErrorCode
        if (index := reported.find(f"{code.value}{SEPARATOR}")) >= 0
    ]
    if not positions:
        return None
    index, code = min(positions)
    return code, index
