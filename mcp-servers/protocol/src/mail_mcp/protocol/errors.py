"""How a failure is reported on the wire.

MCP reports a failure as text. Without an agreed code, a caller could not tell a
message that does not exist from a mailbox it may not read, and would be left
guessing from prose written for a human.

A server prefixes its message with a code; a caller reads the code back. Both
sides tolerate extra text around it, because runtimes wrap error messages.
"""

from __future__ import annotations

from enum import StrEnum

SEPARATOR = ": "


class MailErrorCode(StrEnum):
    """Stable code a mail MCP server reports a failure under."""

    NOT_FOUND = "mail_not_found"
    ACCESS_DENIED = "mail_access_denied"
    UNAVAILABLE = "mail_unavailable"
    PROTOCOL = "mail_protocol"


def encode(code: MailErrorCode, detail: str) -> str:
    """Render a failure as the coded text a caller can decode."""
    return f"{code.value}{SEPARATOR}{detail}"


def decode(reported: str) -> tuple[MailErrorCode, str]:
    """Read the code and detail out of a reported failure.

    The code is searched for rather than expected at the start: a server may
    prefix its own context, and MCP runtimes do exactly that. The earliest code
    wins, so the outcome never depends on declaration order.

    Text carrying no known code is reported as a protocol failure rather than
    guessed at.
    """
    found = _first_code(reported)
    if found is None:
        return MailErrorCode.PROTOCOL, reported
    code, index = found
    detail = reported[index + len(code.value) + len(SEPARATOR) :].strip()
    return code, detail or reported


class MailServerError(Exception):
    """Base class for a failure a mail server reports to its caller.

    The exception types live with the codes so that every server reports the
    same four failures, and a caller only ever has four cases to handle.
    """

    code = MailErrorCode.PROTOCOL

    def reported(self) -> str:
        """Render the failure as the coded text the protocol defines."""
        return encode(self.code, str(self))


class NotFoundError(MailServerError):
    """Raised when the requested message, thread or label does not exist."""

    code = MailErrorCode.NOT_FOUND

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} {identifier!r} was not found")


class AccessDeniedError(MailServerError):
    """Raised when the mail system refuses the access."""

    code = MailErrorCode.ACCESS_DENIED


class UnavailableError(MailServerError):
    """Raised when the mail system cannot be reached."""

    code = MailErrorCode.UNAVAILABLE


class ProtocolError(MailServerError):
    """Raised when the mail system answered something unusable."""

    code = MailErrorCode.PROTOCOL


def _first_code(reported: str) -> tuple[MailErrorCode, int] | None:
    """Return the earliest known code in a reported failure, if any."""
    positions = [
        (index, code)
        for code in MailErrorCode
        if (index := reported.find(f"{code.value}{SEPARATOR}")) >= 0
    ]
    if not positions:
        return None
    index, code = min(positions)
    return code, index
