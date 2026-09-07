"""Calls to the Gmail REST API.

Only this class speaks HTTP to Google. It attaches the token, and it translates
transport and status failures into the mail error family, so nothing above ever
sees a status code.
"""

from __future__ import annotations

from typing import Any

import httpx

from mail_mcp.gmail.credentials import GmailCredentials
from mail_mcp.protocol.errors import (
    AccessDeniedError,
    NotFoundError,
    ProtocolError,
    UnavailableError,
)

BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailApiClient:
    """Sends authenticated requests to the Gmail API.

    One HTTP client is kept for the lifetime of the process: a mailbox query
    fans out into one request per message, and paying a TLS handshake for each
    of them would dominate the response time.
    """

    def __init__(self, credentials: GmailCredentials, *, timeout_seconds: int = 30) -> None:
        self._credentials = credentials
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def get(self, path: str, **parameters: Any) -> dict[str, Any]:
        """Read a resource."""
        return await self._send("GET", path, params=self._query(parameters))

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or modify a resource."""
        return await self._send("POST", path, json=payload)

    async def aclose(self) -> None:
        """Release the HTTP connection pool."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def _send(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send one request and turn a failure into a mail error."""
        token = await self._credentials.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await self._http().request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise UnavailableError(f"Gmail could not be reached: {type(error).__name__}") from error
        return self._decoded(response, path)

    def _http(self) -> httpx.AsyncClient:
        """Return the shared HTTP client, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    @staticmethod
    def _query(parameters: dict[str, Any]) -> dict[str, Any]:
        """Drop the parameters that were not set."""
        return {key: value for key, value in parameters.items() if value is not None}

    @staticmethod
    def _decoded(response: httpx.Response, path: str) -> dict[str, Any]:
        """Return the body, or raise the failure the status describes."""
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError("resource", path)
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise AccessDeniedError(f"Gmail refused {path!r}: {response.status_code}")
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise UnavailableError(f"Gmail failed on {path!r}: {response.status_code}")
        if response.status_code != httpx.codes.OK:
            raise ProtocolError(f"Gmail rejected {path!r}: {response.status_code}")
        if not response.content:
            return {}
        try:
            body: dict[str, Any] = response.json()
        except ValueError as error:
            raise ProtocolError(f"Gmail returned an unreadable body for {path!r}") from error
        return body
