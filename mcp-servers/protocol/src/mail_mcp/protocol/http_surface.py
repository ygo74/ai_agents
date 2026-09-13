"""Serving the mail tools over HTTP, to a caller that proves who it is.

Over stdio, this server's security argument is the operating system: it is a
child process, its Google credential never leaves it, and the caller talks to it
through a pipe nobody else can open.

Over HTTP that argument is gone. The pipe becomes a port, and every process that
can reach the port can read the mailbox. Nothing else about the server changes -
same tools, same payloads - which is exactly why the difference is easy to miss.

So the HTTP surface authenticates, and a server told to serve HTTP without a
token **refuses to start**. Failing to boot is a loud, cheap failure; serving a
mailbox to an unauthenticated network is a quiet, expensive one. The two agents
of this repository already make the same choice for the same reason.

The token is compared in constant time and never logged. It is a shared secret
between two processes of one deployment, not a user credential: it says "you are
the agent I was deployed with", and says nothing about whose mailbox is being
read. That question was already settled - this server holds one credential and
serves one mailbox.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from starlette.applications import Starlette

TOKEN_VARIABLE = "MAIL_MCP_HTTP_TOKEN"  # noqa: S105 - the name of a variable, not its value
HEALTH_PATH = "/healthz"

_BEARER = "bearer"

_logger = logging.getLogger(__name__)


class MissingServerTokenError(RuntimeError):
    """Raised when an HTTP surface was asked for with nothing to authenticate it.

    Deliberately fatal. A server that started anyway would be a mailbox on a
    port, and the only sign of it would be the absence of a line in a log.
    """

    def __init__(self) -> None:
        super().__init__(
            f"serving over HTTP requires {TOKEN_VARIABLE}: this process holds a Google credential, "
            "and an unauthenticated port would hand the mailbox to anything that can reach it"
        )


def required_token(environment: dict[str, str] | None = None) -> str:
    """Return the token the HTTP surface will require, or refuse to serve."""
    source = environment if environment is not None else dict(os.environ)
    token = source.get(TOKEN_VARIABLE, "").strip()
    if not token:
        raise MissingServerTokenError
    return token


def presented_token(header: str | None) -> str:
    """Read the token out of an ``Authorization`` header, whatever its case.

    Both ``Bearer <token>`` and a bare token are accepted. The scheme is a
    convention between two processes we deploy together, and refusing a caller
    over its capitalisation would be a puzzle rather than a control.
    """
    if not header:
        return ""
    parts = header.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == _BEARER:
        return parts[1].strip()
    return header.strip()


def authenticated(header: str | None, expected: str) -> bool:
    """Whether the presented credential matches, compared in constant time.

    Compared as bytes, not as text. Starlette decodes header bytes as latin-1, so
    a caller can present a header holding any byte at all - and
    ``hmac.compare_digest`` raises ``TypeError`` on non-ASCII ``str``. Comparing
    bytes turns "a header we cannot even represent" into a plain refusal rather
    than a traceback in the log of the process holding the Google credential.
    """
    presented = presented_token(header).encode("utf-8", "surrogateescape")
    return hmac.compare_digest(presented, expected.encode("utf-8", "surrogateescape"))


def authenticating(app: Starlette, token: str) -> Starlette:
    """Wrap an application so every request but the health probe carries a token.

    The probe stays open on purpose: an orchestrator has to be able to ask
    whether the process is alive without being handed a credential to do it, and
    the answer - ``{"status": "ok"}`` - discloses nothing about the mailbox.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def guard(request: Request, call_next: Any) -> Any:
        if request.url.path == HEALTH_PATH:
            return await call_next(request)
        if not authenticated(request.headers.get("authorization"), token):
            # No detail: which part was wrong is information a guesser can use,
            # and the operator has the server log.
            _logger.warning("refused an unauthenticated request to %s", request.url.path)
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    app.router.routes.append(Route(HEALTH_PATH, health, methods=["GET"]))
    app.add_middleware(BaseHTTPMiddleware, dispatch=guard)
    return app
