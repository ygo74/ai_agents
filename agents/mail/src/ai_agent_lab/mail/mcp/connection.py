"""Connection to a mail MCP server.

One session is opened for the lifetime of a conversation and closed when it
ends. Opening a connection per call would pay the initialisation handshake -
and, over HTTP, a token exchange - on every message the user reads.

One session, and exactly one. A model routinely calls two mail tools in the same
turn, and the framework runs them concurrently. Without a guard, each of them
opens its own transport; the losers are then garbage collected from whichever
task happens to run last, and anyio refuses to unwind a cancel scope outside the
task that entered it. The visible symptom is not a warning: the transport dies
mid-turn and the mailbox appears to be unavailable.

Transport failures are translated at this boundary. Nothing above ever sees an
anyio cancellation, an HTTP status or a broken pipe: it sees a mail tool that
could not be reached.
"""

from __future__ import annotations

import asyncio
import logging
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
_logger = logging.getLogger(__name__)


class McpConnection:
    """Holds one MCP client session, opened on first use."""

    def __init__(
        self,
        binding: McpServerBinding,
        *,
        timeout_seconds: int = 30,
        auth: httpx.Auth | None = None,
    ) -> None:
        _logger.info("Initializing Mail MCP connection")
        _logger.debug(
            "McpConnection.__init__ arguments: server=%s, transport=%s, "
            "timeout_seconds=%d, authentication_configured=%s",
            binding.server,
            binding.transport.value,
            timeout_seconds,
            auth is not None,
        )
        self._binding = binding
        self._timeout = timeout_seconds
        self._auth = auth
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._opening = asyncio.Lock()

    async def session(self) -> ClientSession:
        """Return the open session, connecting the first time it is needed.

        The check is repeated inside the lock: several callers can pass the
        first one together, and only the first through the door may connect.
        """
        _logger.debug(
            "McpConnection.session arguments: server=%s, transport=%s, already_open=%s",
            self._binding.server,
            self._binding.transport.value,
            self._session is not None,
        )
        if self._session is not None:
            return self._session
        async with self._opening:
            if self._session is None:
                self._session = await self._connect()
            return self._session

    async def aclose(self) -> None:
        """Close the session and release the transport."""
        _logger.info("Closing Mail MCP connection")
        _logger.debug(
            "McpConnection.aclose arguments: server=%s, transport=%s, has_stack=%s",
            self._binding.server,
            self._binding.transport.value,
            self._stack is not None,
        )
        stack, self._stack, self._session = self._stack, None, None
        if stack is None:
            return
        try:
            await stack.aclose()
        except (OSError, RuntimeError, httpx.HTTPError) as error:
            _logger.debug(
                "Mail MCP connection was already unavailable while closing: error_type=%s",
                type(error).__name__,
            )
            # The conversation is over; a server that already went away must not
            # turn a clean exit into a crash.
            return

    async def _connect(self) -> ClientSession:
        """Open the transport and initialise the protocol session."""
        _logger.info("Connecting to Mail MCP server")
        _logger.debug(
            "McpConnection._connect arguments: server=%s, transport=%s, timeout_seconds=%d",
            self._binding.server,
            self._binding.transport.value,
            self._timeout,
        )
        stack = AsyncExitStack()
        try:
            session = await self._open(stack)
            await session.initialize()
        except Exception as error:
            _logger.exception(
                "Mail MCP connection failed: server=%s, transport=%s, error_type=%s",
                self._binding.server,
                self._binding.transport.value,
                type(error).__name__,
            )
            await stack.aclose()
            raise MailToolUnavailableError(
                f"mail MCP server {self._binding.server!r} could not be reached: {type(error).__name__}"
            ) from error
        self._stack = stack
        return session

    async def _open(self, stack: AsyncExitStack) -> ClientSession:
        """Open the transport the binding asks for."""
        _logger.info("Opening Mail MCP transport")
        _logger.debug(
            "McpConnection._open arguments: server=%s, transport=%s, "
            "stack_type=%s, timeout_seconds=%d, authentication_configured=%s",
            self._binding.server,
            self._binding.transport.value,
            type(stack).__name__,
            self._timeout,
            self._auth is not None,
        )
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
        _logger.info("Building Mail MCP stdio server parameters")
        _logger.debug(
            "McpConnection._stdio_parameters arguments: server=%s, command=%s, argument_count=%d",
            self._binding.server,
            self._binding.command,
            len(self._binding.args),
        )
        command = self._binding.command
        return StdioServerParameters(
            command=sys.executable if command == _PYTHON else command,
            args=list(self._binding.args),
        )
