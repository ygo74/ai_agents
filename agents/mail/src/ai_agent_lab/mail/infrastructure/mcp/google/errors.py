"""Failure translation for a third-party server without the native extra."""

from ai_agent_lab.mail.application.errors import MailToolError, MailToolProtocolError
from ai_agent_lab.mail.infrastructure.mcp.failures import tool_failure

_CODES = ("mail_not_found", "mail_access_denied", "mail_unavailable", "mail_protocol")
_SEPARATOR = ": "


def decode_failure(reported: str) -> MailToolError:
    """Preserve recognized legacy errors; do not guess from arbitrary prose."""
    positions = [(index, code) for code in _CODES if (index := reported.find(f"{code}{_SEPARATOR}")) >= 0]
    if not positions:
        return MailToolProtocolError(reported)
    index, code = min(positions)
    detail = reported[index + len(code) + len(_SEPARATOR) :].strip()
    return tool_failure(code, detail or reported)
