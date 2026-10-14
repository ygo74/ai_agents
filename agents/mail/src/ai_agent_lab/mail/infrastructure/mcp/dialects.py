"""Mail dialect factories registered with the generic runtime registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ygo74.agent_runtime.domains.mcp.binding import McpConnection, McpServerBinding
from ygo74.agent_runtime.domains.mcp.dialects import DialectRegistry

from ai_agent_lab.mail.application.errors import MailToolUnavailableError
from ai_agent_lab.mail.application.ports.mail_tools import MailTools
from ai_agent_lab.mail.domain.operation_names import MailToolName
from ai_agent_lab.mail.infrastructure.mcp.google.client import GmailMailTools

NATIVE = "native"
GMAIL = "gmail"

DialectFactory = Callable[[McpServerBinding[MailToolName], McpConnection, str], MailTools]


def _native(binding: McpServerBinding[MailToolName], connection: McpConnection, owner_id: str) -> MailTools:
    """Build the client of a server implementing the mail protocol."""
    try:
        from ai_agent_lab.mail.infrastructure.mcp.native.client import McpMailTools
    except ModuleNotFoundError as error:
        if error.name == "mail_mcp" or (error.name is not None and error.name.startswith("mail_mcp.protocol")):
            raise MailToolUnavailableError(
                "the native Mail dialect requires ai-agent-lab-mail-agent[native]"
            ) from error
        raise

    return McpMailTools(connection, binding, owner_id=owner_id)


def _gmail(binding: McpServerBinding[MailToolName], connection: McpConnection, owner_id: str) -> MailTools:
    """Build the client of the official Gmail server."""
    return GmailMailTools(connection, binding, owner_id=owner_id)


def create_dialect_registry(
    dialects: Mapping[str, DialectFactory] | None = None,
) -> DialectRegistry[MailTools, [McpConnection, str]]:
    """Create the runtime registry populated with Mail's concrete dialects.

    Args:
        dialects: Optional application dialect factories used in place of the defaults.
    """
    return DialectRegistry(
        dialects or {NATIVE: _native, GMAIL: _gmail},
        unavailable=MailToolUnavailableError,
    )
