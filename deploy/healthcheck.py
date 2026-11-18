"""Is this process answering?

Deliberately narrow. A health probe answers one question - is the process
listening and serving - and must not be tempted into answering others.

In particular it does **not** authenticate. All three services here refuse
unauthenticated callers, so a 401 is a perfectly good sign of life: something is
listening, routing, and applying its security policy. Giving the probe a
credential so it could see a 200 would put a credential in the image, in the
compose file and in the orchestrator, to learn nothing more.

Anything that answers is alive. A refused connection, a timeout or a 5xx is not.

Usage::

    python /app/healthcheck.py http://127.0.0.1:8123/v1/models
"""

from __future__ import annotations

import ipaddress
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

TIMEOUT_SECONDS = 4
ALIVE_STATUSES = frozenset({200, 401, 403})


def alive(*urls: str) -> bool:
    """Whether at least one candidate service URL answered.

    Args:
        urls: One or more candidate URLs, usually HTTP and HTTPS loopback URLs
            for the same service listener.
    """
    if not urls:
        return False

    # Divide a single probe budget across the candidate URLs so Docker's overall
    # health-check timeout is not multiplied by each fallback attempt.
    timeout = TIMEOUT_SECONDS / len(urls)
    return any(_probe(url, timeout=timeout) for url in urls)


def _probe(url: str, *, timeout: float) -> bool:
    """Check one URL and treat configured refusal statuses as a live service.

    Args:
        url: Candidate health endpoint to request.
        timeout: Portion of the total health-check time budget for this request.
    """
    try:
        parsed_url = urlsplit(url)
        if (
            parsed_url.scheme.casefold() not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            return False

        context = _tls_context(url) if parsed_url.scheme.casefold() == "https" else None

        with _open_url(url, timeout=timeout, context=context) as response:
            return int(response.status) in ALIVE_STATUSES
    except urllib.error.HTTPError as refusal:
        # It answered. Refusing us is the policy working, not the process dying.
        return int(refusal.code) in ALIVE_STATUSES
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _open_url(url: str, *, timeout: float, context: ssl.SSLContext | None) -> Any:
    """Open one HTTP(S) probe URL without following redirects.

    Args:
        url: Candidate HTTP or HTTPS endpoint to request.
        timeout: Maximum socket wait for this candidate.
        context: HTTPS verification policy, or ``None`` for plain HTTP.
    """
    handlers: list[urllib.request.BaseHandler] = [_NoRedirectHandler()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(url, timeout=timeout)


def _tls_context(url: str) -> ssl.SSLContext:
    """Use ordinary verification except for a local loopback liveness probe.

    Args:
        url: HTTPS health endpoint whose host determines the verification policy.
    """
    context = ssl.create_default_context()
    hostname = urlsplit(url).hostname or ""
    if _is_loopback(hostname):
        # A public certificate usually does not name the container's loopback
        # address. This exception is safe here because this script probes only
        # whether the local listener answers; external clients still verify TLS.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _is_loopback(hostname: str) -> bool:
    """Whether a URL host is localhost or an IP loopback address.

    Args:
        hostname: Host component parsed from the probe URL.
    """
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent liveness checks from leaving the explicitly configured URL."""

    def redirect_request(
        self,
        _request: Any,
        _response: Any,
        _code: int,
        _message: str,
        _headers: Any,
        _new_url: str,
    ) -> None:
        """Refuse a redirect rather than carrying the original TLS policy over.

        Args:
            _request: Request that received the redirect response.
            _response: Response object being closed before a redirect.
            _code: HTTP redirect status code.
            _message: HTTP response message.
            _headers: Response headers, including any redirect location.
            _new_url: URL proposed by the remote response.
        """
        return


def main() -> int:
    """Return 0 when any supplied service URL answered, 1 otherwise."""
    if len(sys.argv) < 2:
        print("usage: healthcheck.py <url> [<fallback-url> ...]", file=sys.stderr)
        return 2
    return 0 if alive(*sys.argv[1:]) else 1


if __name__ == "__main__":
    sys.exit(main())
