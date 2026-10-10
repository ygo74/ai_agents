"""Wiki-specific errors raised while loading MCP configuration."""

from __future__ import annotations

from ai_agent_lab.wiki.wiki_errors import WikiToolProtocolError


class McpBindingError(WikiToolProtocolError):
    """A delivered Wiki MCP binding cannot be used as declared."""
