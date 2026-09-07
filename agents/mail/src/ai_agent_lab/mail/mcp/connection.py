"""Connection to a mail MCP server.

One session is opened for the lifetime of a conversation and closed when it
ends. Opening a connection per call would pay the initialisation handshake -
and, over HTTP, a token exchange - on every message the user reads.

Transport failures are translated at this boundary. Nothing above ever sees an
anyio cancellation, an HTTP status or a broken pipe: it sees a mail tool that
could not be reached.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from datetime import timedelta

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from ai_agent_lab.mail.mail_errors import MailToolUnavailableError
from ai_agent_lab.mail.mcp.binding import McpServerBinding, McpTransport

_PYTHON = "python"


class McpConnection:
    """Holds one MCP client session, opened on first use."""

    def __init__(
        self,
        binding: McpServerBinding,
        *,
        timeout_seconds: int = 30,
        auth: httpx.Auth | None = None,
    ) -> None:
        self._binding = binding
        self._timeout = timeout_seconds
        self._auth = auth
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def session(self) -> ClientSession:
        """Return the open session, connecting the first time it is needed."""
        if self._session is not None:
            return self._session
        self._session = await self._connect()
        return self._session

    async def aclose(self) -> None:
        """Close the session and release the transport."""
        stack, self._stack, self._session = self._stack, None, None
        if stack is None:
            return
        try:
            await stack.aclose()
        except (OSError, RuntimeError, httpx.HTTPError):
            # The conversation is over; a server that already went away must not
            # turn a clean exit into a crash.
            return

    async def _connect(self) -> ClientSession:
        """Open the transport and initialise the protocol session."""
        stack = AsyncExitStack()
        try:
            session = await self._open(stack)
            await session.initialize()
        except Exception as error:
            await stack.aclose()
            raise MailToolUnavailableError(
                f"mail MCP server {self._binding.server!r} could not be reached: {type(error).__name__}"
            ) from error
        self._stack = stack
        return session

    async def _open(self, stack: AsyncExitStack) -> ClientSession:
        """Open the transport the binding asks for."""
        if self._binding.transport is McpTransport.HTTP:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(self._binding.url, timeout=self._timeout, auth=self._auth)
            )
        else:
            read, write = await stack.enter_async_context(stdio_client(self._stdio_parameters()))
        return await stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self._timeout))
        )

    def _stdio_parameters(self) -> StdioServerParameters:
        """Describe the process to start for a stdio server.

        ``python`` is resolved to the interpreter currently running, so a server
        declared in configuration starts in this virtual environment rather than
        in whatever happens to be first on the PATH.
        """
        command = self._binding.command
        return StdioServerParameters(
            command=sys.executable if command == _PYTHON else command,
            args=list(self._binding.args),
        )
