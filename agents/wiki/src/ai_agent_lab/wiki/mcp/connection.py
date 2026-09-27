"""Wiki error adaptation for the runtime's generic MCP connection."""

from __future__ import annotations

from collections.abc import Mapping

from ygo74.agent_runtime.domains.mcp.binding import McpConnection as RuntimeMcpConnection

from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.mcp.binding import McpServerBinding
from ai_agent_lab.wiki.wiki_errors import WikiToolUnavailableError


class McpConnection(RuntimeMcpConnection):
    """Use the shared connection lifecycle and retain Wiki boundary errors."""

    def __init__(
        self,
        binding: McpServerBinding[WikiToolName],
        *,
        timeout_seconds: int = 30,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            binding,
            timeout_seconds=timeout_seconds,
            headers=headers,
            unavailable=WikiToolUnavailableError,
        )
