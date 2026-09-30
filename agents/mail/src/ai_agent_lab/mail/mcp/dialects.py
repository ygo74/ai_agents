"""Mail dialect factories registered with the generic runtime registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ygo74.agent_runtime.domains.mcp.dialects import DialectRegistry

from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.mail_errors import MailToolUnavailableError
from ai_agent_lab.mail.mcp.binding import McpServerBinding
from ai_agent_lab.mail.mcp.connection import McpConnection
from ai_agent_lab.mail.mcp.google.client import GmailMailTools
from ai_agent_lab.mail.mcp.native.client import McpMailTools
from ai_agent_lab.mail.tools_port import MailTools

NATIVE = "native"
GMAIL = "gmail"

DialectFactory = Callable[[McpServerBinding[MailToolName], McpConnection, str], MailTools]


def _native(binding: McpServerBinding[MailToolName], connection: McpConnection, owner_id: str) -> MailTools:
    """Build the client of a server implementing the mail protocol."""
    return McpMailTools(connection, binding, owner_id=owner_id)


def _gmail(binding: McpServerBinding[MailToolName], connection: McpConnection, owner_id: str) -> MailTools:
    """Build the client of the official Gmail server."""
    return GmailMailTools(connection, binding, owner_id=owner_id)


class MailDialectRegistry(DialectRegistry[MailTools, [McpConnection, str]]):
    """Supply Mail's dialect choices to the shared registry mechanics."""

    def __init__(self, dialects: Mapping[str, DialectFactory] | None = None) -> None:
        super().__init__(dialects or {NATIVE: _native, GMAIL: _gmail}, unavailable=MailToolUnavailableError)
