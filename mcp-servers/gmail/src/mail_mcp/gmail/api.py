"""Calls to the Gmail REST API.

Only this class speaks HTTP to Google. It attaches the token, and it translates
transport and status failures into the mail error family, so nothing above ever
sees a status code.

It also retries what is worth retrying. A mailbox query fans out into one
request per message, so a single rate-limited or dropped request would fail a
whole search that was seconds from succeeding. Retrying is limited to failures
that say nothing happened - a refused connection, a rate limit, a server error -
and deliberately not applied to a request whose effect is unknown.
"""

from __future__ import annotations

import asyncio
import logging
import random
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

# Statuses that mean "not now" rather than "no". Everything else is an answer.
_RETRYABLE_STATUSES = frozenset(
    {
        httpx.codes.TOO_MANY_REQUESTS,
        httpx.codes.INTERNAL_SERVER_ERROR,
        httpx.codes.BAD_GATEWAY,
        httpx.codes.SERVICE_UNAVAILABLE,
        httpx.codes.GATEWAY_TIMEOUT,
    }
)

_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.5

_logger = logging.getLogger(__name__)


class GmailConflictError(ProtocolError):
    """Raised when Gmail refuses a creation because the resource already exists.

    This never reaches a caller. It exists so that the one place that can
    recover - creating a label that was made between the check and the write -
    can tell that case apart from a genuine rejection.
    """


class _Transient(Exception):  # noqa: N818 - an internal signal, never reported
    """Signals a failure worth another attempt."""


class GmailApiClient:
    """Sends authenticated requests to the Gmail API.

    One HTTP client is kept for the lifetime of the process: a mailbox query
    fans out into one request per message, and paying a TLS handshake for each
    of them would dominate the response time.
    """

    def __init__(
        self,
        credentials: GmailCredentials,
        *,
        timeout_seconds: int = 30,
        attempts: int = _ATTEMPTS,
    ) -> None:
        self._credentials = credentials
        self._timeout = timeout_seconds
        self._attempts = max(1, attempts)
        self._client: httpx.AsyncClient | None = None

    async def get(self, path: str, **parameters: Any) -> dict[str, Any]:
        """Read a resource, retrying a failure that changed nothing."""
        return await self._send("GET", path, retry=True, params=self._query(parameters))

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or modify a resource.

        Not retried. A request that timed out may still have been applied, and
        sending it again could file a message twice or create a second draft.
        Reporting a failure that did not happen is a nuisance; performing an
        operation twice without being asked is a defect.
        """
        return await self._send("POST", path, retry=False, json=payload)

    async def delete(self, path: str) -> None:
        """Remove a resource.

        Gmail answers a deletion with an empty body, so there is nothing to
        return and nothing for a caller to misread as a result.
        """
        await self._send("DELETE", path, retry=False)

    async def aclose(self) -> None:
        """Release the HTTP connection pool."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def _send(self, method: str, path: str, *, retry: bool, **kwargs: Any) -> dict[str, Any]:
        """Send one request, retrying it when that is safe and useful."""
        attempts = self._attempts if retry else 1
        last = ""
        for attempt in range(1, attempts + 1):
            try:
                return await self._attempt(method, path, **kwargs)
            except _Transient as transient:
                last = str(transient)
                if attempt == attempts:
                    raise UnavailableError(f"Gmail did not answer {path!r}: {last}") from transient
                await self._pause(attempt, path, last)
        raise UnavailableError(f"Gmail did not answer {path!r}: {last}")

    @staticmethod
    async def _pause(attempt: int, path: str, reason: str) -> None:
        """Wait before trying again.

        The delay grows and carries a little randomness, so several requests
        failing together do not come back in step and repeat the burst that
        rate-limited them.
        """
        delay = _BACKOFF_SECONDS * (2 ** (attempt - 1)) * (1 + random.random())  # noqa: S311 - jitter, not a secret
        _logger.info("Gmail %s on %s, retrying in %.1fs", reason, path, delay)
        await asyncio.sleep(delay)

    async def _attempt(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send one request, turning a retryable failure into a signal."""
        token = await self._credentials.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await self._http().request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise _Transient(type(error).__name__) from error
        if response.status_code in _RETRYABLE_STATUSES:
            raise _Transient(f"HTTP {response.status_code}")
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
        if response.status_code == httpx.codes.CONFLICT:
            raise GmailConflictError(f"Gmail reports {path!r} already exists")
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise UnavailableError(f"Gmail failed on {path!r}: {response.status_code}")
        if response.status_code not in (httpx.codes.OK, httpx.codes.NO_CONTENT):
            raise ProtocolError(f"Gmail rejected {path!r}: {response.status_code}")
        if not response.content:
            return {}
        try:
            body: dict[str, Any] = response.json()
        except ValueError as error:
            raise ProtocolError(f"Gmail returned an unreadable body for {path!r}") from error
        return body
