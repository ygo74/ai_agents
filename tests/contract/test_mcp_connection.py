"""Tests of the connection to a mail MCP server.

One property matters above the others: a turn in which the model calls two mail
tools must open one session, not two. It is the ordinary case - "find the
messages and list the labels" - and getting it wrong is not a warning. The
surplus transports are unwound from whichever task collects them, anyio refuses
to leave a cancel scope outside the task that entered it, and the session dies
in the middle of the turn. What the user sees is a mailbox that went away.
"""

from __future__ import annotations

import asyncio

import pytest

from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.mcp.binding import McpServerBinding, McpTransport
from ai_agent_lab.mail.mcp.connection import McpConnection

DATASET = "data/mail/sample_mailbox.json"

BINDING = McpServerBinding(
    server="reference",
    transport=McpTransport.STDIO,
    capabilities=tuple(MailToolName),
    tools={name.value: name.value for name in MailToolName},
    dialect="native",
    command="python",
    args=("-m", "mail_mcp.reference.server", "--dataset", DATASET),
)


class TestOneConversationOpensOneSession:
    """Concurrent tool calls share the session they find."""

    async def test_concurrent_callers_get_the_same_session(self):
        connection = McpConnection(BINDING, timeout_seconds=30)
        try:
            sessions = await asyncio.gather(*(connection.session() for _ in range(8)))

            assert len({id(session) for session in sessions}) == 1
        finally:
            await connection.aclose()

    async def test_the_session_still_serves_calls_made_at_once(self):
        """The guard must not have serialised the conversation into a queue."""
        connection = McpConnection(BINDING, timeout_seconds=30)
        try:
            session = await connection.session()
            results = await asyncio.gather(
                session.call_tool("list_labels", {"owner": "local-user"}),
                session.call_tool("search_mail", {"owner": "local-user", "limit": 3}),
                session.call_tool("list_labels", {"owner": "local-user"}),
            )

            assert all(not result.isError for result in results)
        finally:
            await connection.aclose()

    async def test_a_later_caller_reuses_the_open_session(self):
        connection = McpConnection(BINDING, timeout_seconds=30)
        try:
            first = await connection.session()
            second = await connection.session()

            assert first is second
        finally:
            await connection.aclose()

    async def test_closing_twice_is_harmless(self):
        connection = McpConnection(BINDING, timeout_seconds=30)
        await connection.session()

        await connection.aclose()
        await connection.aclose()


class TestAnUnreachableServerIsReported:
    """A server that cannot be started is a mail failure, not a traceback."""

    async def test_a_missing_server_module_is_reported_as_unavailable(self):
        from ai_agent_lab.mail.mail_errors import MailToolUnavailableError

        binding = McpServerBinding(
            server="absent",
            transport=McpTransport.STDIO,
            capabilities=tuple(MailToolName),
            tools={name.value: name.value for name in MailToolName},
            dialect="native",
            command="python",
            args=("-m", "mail_mcp.no_such_server"),
        )
        connection = McpConnection(binding, timeout_seconds=10)

        with pytest.raises(MailToolUnavailableError):
            await connection.session()

        await connection.aclose()
