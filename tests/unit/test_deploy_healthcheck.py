"""Tests for container health probes in HTTP and direct HTTPS modes."""

from __future__ import annotations

import ssl
import urllib.error
from contextlib import nullcontext
from typing import Any

import pytest
from deploy import healthcheck


def test_alive_preserves_single_http_probe(monkeypatch) -> None:
    """Keep the one-URL HTTP probe used by the standalone MCP server."""
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        healthcheck,
        "_open_url",
        lambda url, **kwargs: calls.append((url, kwargs)) or nullcontext(_Response(401)),
    )

    assert healthcheck.alive("http://127.0.0.1:9100/healthz") is True
    assert len(calls) == 1
    assert calls[0][1]["context"] is None


def test_alive_falls_back_to_loopback_https_probe(monkeypatch) -> None:
    """Use HTTPS when the local listener does not answer its HTTP candidate."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def open_url(url: str, **kwargs: Any):
        calls.append((url, kwargs))
        if url.startswith("http:"):
            raise urllib.error.URLError("TLS listener does not speak HTTP")
        return nullcontext(_Response(403))

    monkeypatch.setattr(healthcheck, "_open_url", open_url)

    assert (
        healthcheck.alive(
            "http://127.0.0.1:8123/v1/models",
            "https://127.0.0.1:8123/v1/models",
        )
        is True
    )
    assert len(calls) == 2
    tls_context = calls[1][1]["context"]
    assert isinstance(tls_context, ssl.SSLContext)
    assert tls_context.verify_mode == ssl.CERT_NONE
    assert tls_context.check_hostname is False
    assert all(call[1]["timeout"] <= healthcheck.TIMEOUT_SECONDS / 2 for call in calls)


def test_alive_verifies_non_loopback_https_certificate(monkeypatch) -> None:
    """Keep normal certificate verification for HTTPS targets outside loopback."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        healthcheck, "_open_url", lambda url, **kwargs: calls.append(kwargs) or nullcontext(_Response(200))
    )

    assert healthcheck.alive("https://agent.example.test/healthz") is True

    tls_context = calls[0]["context"]
    assert tls_context.verify_mode == ssl.CERT_REQUIRED
    assert tls_context.check_hostname is True


def test_alive_returns_false_when_every_candidate_fails(monkeypatch) -> None:
    """Report a failed health probe only after each configured URL fails."""
    attempted_urls: list[str] = []

    def open_url(url: str, **kwargs: Any):
        attempted_urls.append(url)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(healthcheck, "_open_url", open_url)

    assert healthcheck.alive("http://127.0.0.1:8123/healthz", "https://127.0.0.1:8123/healthz") is False
    assert len(attempted_urls) == 2


def test_alive_rejects_credentials_in_probe_urls(monkeypatch) -> None:
    """Keep a probe URL from carrying credentials into the health-check process."""
    monkeypatch.setattr(healthcheck, "_open_url", lambda *args, **kwargs: pytest.fail("URL must be rejected"))

    assert healthcheck.alive("https://user:secret@127.0.0.1:8123/healthz") is False


def test_redirect_handler_refuses_to_follow_a_different_url() -> None:
    """Keep a loopback-only TLS exception from following a remote redirect."""
    handler = healthcheck._NoRedirectHandler()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example.test") is None


class _Response:
    """Minimal context-managed response returned by a patched URL opener."""

    def __init__(self, status: int) -> None:
        """Store the HTTP status used by the liveness probe."""
        self.status = status

    def __enter__(self) -> _Response:
        """Return this response from a ``with`` statement."""
        return self

    def __exit__(self, *args: object) -> None:
        """Allow the liveness probe to close the response context."""
