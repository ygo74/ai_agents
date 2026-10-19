"""Native wire decoding belongs exclusively to this dialect."""

from ai_agent_lab.mail.application.errors import MailToolError
from ai_agent_lab.mail.infrastructure.mcp.failures import tool_failure
from mail_mcp.protocol.errors import decode


def decode_failure(reported: str) -> MailToolError:
    """Reuse the native protocol decoder and translate its result."""
    code, detail = decode(reported)
    return tool_failure(code.value, detail)
