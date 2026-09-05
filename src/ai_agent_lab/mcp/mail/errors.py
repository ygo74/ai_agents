"""Errors crossing the mail MCP boundary.

Transport and protocol failures never leak upwards. The MCP client translates
them into these domain-meaningful exceptions so that skills and the application
reason about mail concepts, not about HTTP status codes or JSON-RPC frames.
"""

from __future__ import annotations

from ai_agent_lab.domain.errors import DomainError


class MailToolError(DomainError):
    """Base class for every failure of a mail MCP tool."""


class MailNotFoundError(MailToolError):
    """Raised when the requested message, thread or label does not exist."""

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} {identifier!r} was not found")
        self.resource = resource
        self.identifier = identifier


class MailAccessDeniedError(MailToolError):
    """Raised when the source system refuses access for the calling user.

    The source system remains the authority on authorisation; this error carries
    its refusal without reinterpreting it.
    """

    def __init__(self, identifier: str) -> None:
        super().__init__(f"access to {identifier!r} was denied by the mail system")
        self.identifier = identifier


class MailToolUnavailableError(MailToolError):
    """Raised when the mail MCP server is unreachable or timed out."""


class MailToolProtocolError(MailToolError):
    """Raised when the mail MCP server returned a payload the domain rejects.

    An unexpected payload is an error, never a silently accepted partial result.
    """
