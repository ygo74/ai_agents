"""Presenting a shared secret to a mail MCP server deployed alongside.

Not a user credential, and the distinction matters. The secret says "you are the
agent I was deployed with"; it says nothing about whose mailbox is being read,
because that was already settled by the Google credential the server holds.

It is carried in an ``Authorization`` header and nowhere else: never in a log,
never in a prompt, never in a ``UserContext``.
"""

from __future__ import annotations

from collections.abc import Generator

import httpx


class BearerTokenAuth(httpx.Auth):
    """Adds a bearer token to every request to the bound server."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("a bearer token cannot be empty")
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        """Attach the credential, once, to the outgoing request."""
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request

    def __repr__(self) -> str:
        """Redacted representation: never reveals the secret."""
        return f"BearerTokenAuth(length={len(self._token)})"

    def __str__(self) -> str:
        """Redacted representation, so f-strings cannot leak the secret."""
        return self.__repr__()
