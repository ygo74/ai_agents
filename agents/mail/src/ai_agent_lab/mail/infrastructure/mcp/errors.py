"""Mail-specific errors raised while loading MCP configuration."""

from __future__ import annotations

from ai_agent_lab.mail.application.errors import MailToolProtocolError


class McpBindingError(MailToolProtocolError):
    """A delivered Mail MCP binding cannot be used as declared."""
