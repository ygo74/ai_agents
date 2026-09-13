"""Consent on the loopback interface.

The authorisation server sends the person back to a URL we control. Listening on
``127.0.0.1`` keeps the authorisation code on the machine: it never crosses a
network and never passes through a third party.

The listener serves exactly one redirect and stops, so nothing is left
accepting connections once consent is over.
"""

from __future__ import annotations

import logging
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import anyio

from ai_agent_lab.core.errors import DomainError

LOOPBACK = "127.0.0.1"
CALLBACK_PATH = "/oauth/callback"

_DONE = (
    "<html><body><h3>Authorisation received.</h3>"
    "<p>You can close this tab and return to the terminal.</p></body></html>"
)
_logger = logging.getLogger(__name__)


class AuthorisationFailedError(DomainError):
    """Raised when consent did not produce an authorisation code."""


class LoopbackConsent:
    """Sends a person to an authorisation page and catches the redirect."""

    def __init__(self, port: int) -> None:
        _logger.info("Initializing Mail OAuth loopback consent")
        _logger.debug("LoopbackConsent.__init__ arguments: port=%d", port)
        self._port = port

    @property
    def redirect_uri(self) -> str:
        """Where the authorisation server must send the person back."""
        return f"http://localhost:{self._port}{CALLBACK_PATH}"

    async def open_consent(self, authorization_url: str) -> None:
        """Send the person to the authorisation page."""
        _logger.info("Opening Mail OAuth consent page")
        _logger.debug(
            "LoopbackConsent.open_consent arguments: authorization_url_length=%d",
            len(authorization_url),
        )
        print(f"\nApprove the access in your browser:\n  {authorization_url}\n")
        webbrowser.open(authorization_url)

    async def await_code(self) -> tuple[str, str | None]:
        """Wait for the redirect and return the code and state it carried."""
        _logger.info("Waiting for Mail OAuth loopback callback")
        _logger.debug("LoopbackConsent.await_code arguments: port=%d", self._port)
        return await anyio.to_thread.run_sync(self._serve_once)

    def _serve_once(self) -> tuple[str, str | None]:
        """Serve exactly one redirect, then stop listening."""
        _logger.info("Serving one Mail OAuth loopback callback")
        _logger.debug("LoopbackConsent._serve_once arguments: port=%d", self._port)
        captured: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                captured.update({key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_DONE.encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                """Keep the authorisation code out of the console."""
                del format, args

        with HTTPServer((LOOPBACK, self._port), Handler) as server:
            server.handle_request()

        if "code" not in captured:
            raise AuthorisationFailedError(f"authorisation failed: {captured.get('error', 'no code was returned')}")
        return captured["code"], captured.get("state")
