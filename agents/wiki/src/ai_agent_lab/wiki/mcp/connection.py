"""Connection to a wiki MCP server.

One session is opened for the lifetime of a conversation and closed when it ends.
Opening a connection per call would pay the initialisation handshake - and, over
HTTP, a token exchange - on every question the user asks.

One session, and exactly one. A model routinely calls two wiki tools in the same
turn, and the framework runs them concurrently. Without a guard, each of them
opens its own transport; the losers are then garbage collected from whichever
task happens to run last, and anyio refuses to unwind a cancel scope outside the
task that entered it. The visible symptom is not a warning: the transport dies
mid-turn and the wiki appears to be unavailable.

Transport failures are translated at this boundary. Nothing above ever sees an
anyio cancellation, an HTTP status or a broken pipe: it sees a wiki tool that
could not be reached.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from contextlib import AsyncExitStack
from datetime import timedelta

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from ai_agent_lab.wiki.mcp.binding import McpServerBinding, McpTransport
from ai_agent_lab.wiki.wiki_errors import WikiToolUnavailableError

_PYTHON = "python"


class McpConnection:
    """Holds one MCP client session, opened on first use.

    A connection is built for **one caller**. That matters over HTTP: the server
    reads an ``Authorization`` header to decide whose wiki it is serving, and the
    header is fixed for the lifetime of the session. Sharing one connection
    between two people would serve the second one the first one's view.
    """

    def __init__(
        self,
        binding: McpServerBinding,
        *,
        timeout_seconds: int = 30,
        auth: httpx.Auth | None = None,
        headers: Mapping[str, str] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._binding = binding
        self._timeout = timeout_seconds
        self._auth = auth
        self._headers = dict(headers or {})
        self._environment = dict(environment if environment is not None else os.environ)
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._opening = asyncio.Lock()

    async def session(self) -> ClientSession:
        """Return the open session, connecting the first time it is needed.

        The check is repeated inside the lock: several callers can pass the first
        one together, and only the first through the door may connect.
        """
        if self._session is not None:
            return self._session
        async with self._opening:
            if self._session is None:
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
            raise WikiToolUnavailableError(
                f"wiki MCP server {self._binding.server!r} could not be reached: {type(error).__name__}"
            ) from error
        self._stack = stack
        return session

    async def _open(self, stack: AsyncExitStack) -> ClientSession:
        """Open the transport the binding asks for."""
        if self._binding.transport is McpTransport.HTTP:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(
                    self._binding.url,
                    headers=self._headers or None,
                    timeout=self._timeout,
                    auth=self._auth,
                )
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
            env=self._server_environment(),
        )

    def _server_environment(self) -> dict[str, str] | None:
        """Resolve the environment variables the server process needs.

        The binding names variables; their values are read here, from the ambient
        environment, and handed to the child process. They are never logged and
        never travel any further: a credential belongs to the server process and
        to nothing else.

        A variable the binding asks for and the environment does not hold is
        refused now. Starting the server anyway would produce an authentication
        failure several calls later, which is a much harder thing to read.
        """
        wanted = self._binding.env
        if not wanted:
            return None

        resolved: dict[str, str] = {}
        missing: list[str] = []
        for name, source in wanted.items():
            variable = source or name
            value = self._environment.get(variable)
            if value is None:
                missing.append(variable)
            else:
                resolved[name] = value

        if missing:
            raise WikiToolUnavailableError(
                f"wiki MCP server {self._binding.server!r} needs environment variable(s) {sorted(missing)}"
            )
        return resolved
