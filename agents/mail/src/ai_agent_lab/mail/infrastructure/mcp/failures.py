"""Translate decoded MCP error codes into application exceptions."""

from ai_agent_lab.mail.application.errors import (
    MailAccessDeniedError,
    MailNotFoundError,
    MailToolError,
    MailToolProtocolError,
    MailToolUnavailableError,
)


def tool_failure(code: str, detail: str) -> MailToolError:
    """Translate a dialect's error code without exposing the wire contract."""
    if code == "mail_not_found":
        return MailNotFoundError(message=detail)
    if code == "mail_access_denied":
        return MailAccessDeniedError(message=detail)
    if code == "mail_unavailable":
        return MailToolUnavailableError(detail)
    return MailToolProtocolError(detail)
