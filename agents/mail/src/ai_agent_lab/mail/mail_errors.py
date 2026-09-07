"""Errors crossing the mail MCP boundary.

Transport and protocol failures never leak upwards. The MCP client translates
them into these domain-meaningful exceptions so that skills and the application
reason about mail concepts, not about HTTP status codes or JSON-RPC frames.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from ai_agent_lab.core.errors import DomainError


class MailToolError(DomainError):
    """Base class for every failure of a mail MCP tool."""


class MailErrorCode(StrEnum):
    """Stable code a mail MCP server prefixes its failures with.

    A failure crossing the MCP boundary arrives as text. Without an agreed code
    the client can only guess, and a message that does not exist would be
    indistinguishable from a mailbox it may not read. The code keeps the
    distinction, and is part of the contract a server implements.
    """

    NOT_FOUND = "mail_not_found"
    ACCESS_DENIED = "mail_access_denied"
    UNAVAILABLE = "mail_unavailable"
    PROTOCOL = "mail_protocol"


class MailNotFoundError(MailToolError):
    """Raised when the requested message, thread or label does not exist."""

    def __init__(self, resource: str = "", identifier: str = "", *, message: str = "") -> None:
        super().__init__(message or f"{resource} {identifier!r} was not found")
        self.resource = resource
        self.identifier = identifier


class MailAccessDeniedError(MailToolError):
    """Raised when the source system refuses access for the calling user.

    The source system remains the authority on authorisation; this error carries
    its refusal without reinterpreting it.
    """

    def __init__(self, identifier: str = "", *, message: str = "") -> None:
        super().__init__(message or f"access to {identifier!r} was denied by the mail system")
        self.identifier = identifier


class MailToolUnavailableError(MailToolError):
    """Raised when the mail MCP server is unreachable or timed out."""


class MailToolProtocolError(MailToolError):
    """Raised when the mail MCP server returned a payload the domain rejects.

    An unexpected payload is an error, never a silently accepted partial result.
    """


_SEPARATOR = ": "


def code_of(error: MailToolError) -> MailErrorCode:
    """Return the code a server should report a failure under."""
    if isinstance(error, MailNotFoundError):
        return MailErrorCode.NOT_FOUND
    if isinstance(error, MailAccessDeniedError):
        return MailErrorCode.ACCESS_DENIED
    if isinstance(error, MailToolUnavailableError):
        return MailErrorCode.UNAVAILABLE
    return MailErrorCode.PROTOCOL


def encode_failure(error: MailToolError) -> str:
    """Render a failure as the coded text a client can decode."""
    return f"{code_of(error).value}{_SEPARATOR}{error}"


def decode_failure(reported: str) -> MailToolError:
    """Rebuild the failure a server reported.

    The code is searched for rather than expected at the start: a server is
    free to prefix its own context, and the MCP runtime does exactly that. The
    earliest code wins, so the outcome never depends on dictionary order.

    A server that does not speak our codes still fails loudly: its text is kept
    and reported as a protocol error rather than guessed at.
    """
    found = _first_code(reported)
    if found is None:
        return MailToolProtocolError(reported)
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


_FAILURES: dict[str, Callable[[str], MailToolError]] = {
    MailErrorCode.NOT_FOUND.value: lambda detail: MailNotFoundError(message=detail),
    MailErrorCode.ACCESS_DENIED.value: lambda detail: MailAccessDeniedError(message=detail),
    MailErrorCode.UNAVAILABLE.value: MailToolUnavailableError,
    MailErrorCode.PROTOCOL.value: MailToolProtocolError,
}
