"""Mail error adaptation for the runtime's generic MCP connection."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
from ygo74.agent_runtime.domains.mcp.binding import McpConnection as RuntimeMcpConnection

from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.mail_errors import MailToolUnavailableError
from ai_agent_lab.mail.mcp.binding import McpServerBinding


class McpConnection(RuntimeMcpConnection):
    """Use the shared connection lifecycle and retain Mail boundary errors."""

    def __init__(
        self,
        binding: McpServerBinding[MailToolName],
        *,
        timeout_seconds: int = 30,
        auth: httpx.Auth | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            binding,
            timeout_seconds=timeout_seconds,
            auth=auth,
            headers=headers,
            unavailable=MailToolUnavailableError,
        )
