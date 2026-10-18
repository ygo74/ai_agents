"""Wire error codes and binding errors for Wiki MCP adapters."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from ai_agent_lab.wiki.domain.tool_errors import (
    WikiAccessDeniedError,
    WikiConcurrentEditError,
    WikiNotFoundError,
    WikiToolError,
    WikiToolProtocolError,
    WikiToolUnavailableError,
)


class WikiErrorCode(StrEnum):
    """Stable code a Wiki MCP server prefixes its failures with."""

    NOT_FOUND = "wiki_not_found"
    ACCESS_DENIED = "wiki_access_denied"
    CONFLICT = "wiki_conflict"
    UNAVAILABLE = "wiki_unavailable"
    PROTOCOL = "wiki_protocol"


_SEPARATOR = ": "


def code_of(error: WikiToolError) -> WikiErrorCode:
    """Return the MCP wire code for a Wiki tool error."""
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
    """Render a Wiki tool failure in the MCP text format."""
    return f"{code_of(error).value}{_SEPARATOR}{error}"


def decode_failure(reported: str) -> WikiToolError:
    """Translate an MCP failure string into a Wiki tool error.

    The code is searched rather than expected at the start: a server may prefix
    its own context, and the earliest known code determines the result.
    """
    positions = [
        (index, code)
        for code in _FAILURES
        if (index := reported.find(f"{code}{_SEPARATOR}")) >= 0
    ]
    if not positions:
        return WikiToolProtocolError(reported)
    index, code = min(positions)
    detail = reported[index + len(code) + len(_SEPARATOR) :].strip()
    return _FAILURES[code](detail or reported)


_FAILURES: dict[str, Callable[[str], WikiToolError]] = {
    WikiErrorCode.NOT_FOUND.value: lambda detail: WikiNotFoundError(message=detail),
    WikiErrorCode.ACCESS_DENIED.value: lambda detail: WikiAccessDeniedError(message=detail),
    WikiErrorCode.CONFLICT.value: lambda detail: WikiConcurrentEditError(message=detail),
    WikiErrorCode.UNAVAILABLE.value: WikiToolUnavailableError,
    WikiErrorCode.PROTOCOL.value: WikiToolProtocolError,
}


class McpBindingError(WikiToolProtocolError):
    """A delivered Wiki MCP binding cannot be used as declared."""
