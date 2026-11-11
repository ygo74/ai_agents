"""Small async MCP client helper for real in-process agent host contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def connected_mcp_session(
    app: FastAPI,
    headers: Mapping[str, str],
) -> AsyncIterator[ClientSession]:
    """Initialize one SDK client session against the application's `/mcp` route.

    Args:
        app: The actual FastAPI service built by the agent composition root.
        headers: Authentication headers sent on MCP transport requests.
    """
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent.test",
            headers=dict(headers),
        ) as http,
        streamable_http_client(
            "http://agent.test/mcp",
            http_client=http,
        ) as (read_stream, write_stream, _get_session_id),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session


async def invoke_agent(
    session: ClientSession,
    message: str,
    *,
    conversation_id: str = "default",
    arguments: Mapping[str, Any] | None = None,
):
    """Call the public agent tool and return the MCP SDK result.

    Args:
        session: Initialized MCP client session.
        message: User-authored text sent to the agent.
        conversation_id: Caller-scoped conversation identifier.
        arguments: Optional additional tool fields used by identity-spoofing tests.
    """
    tool_arguments = {"message": message, "conversation_id": conversation_id}
    if arguments:
        tool_arguments.update(arguments)
    return await session.call_tool("invoke_agent", tool_arguments)
