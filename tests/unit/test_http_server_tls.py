"""Tests for direct TLS options on the Mail and Wiki HTTP launchers."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

LAUNCHERS = (
    ("ai_agent_lab.mail.adapters.http.server", "MailEnvironmentFile"),
    ("ai_agent_lab.wiki.adapters.http.server", "WikiEnvironmentFile"),
)


@pytest.mark.parametrize(("module_name", "environment_loader_name"), LAUNCHERS)
def test_launcher_preserves_http_default(
    module_name: str,
    environment_loader_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start Uvicorn without TLS options when no certificate pair is supplied."""
    module = importlib.import_module(module_name)
    environment_loader = getattr(module, environment_loader_name)
    monkeypatch.setattr(environment_loader, "load", lambda self, path=None: None)
    monkeypatch.setattr(sys, "argv", ["agent-http"])
    uvicorn_calls: list[dict[str, object]] = []
    monkeypatch.setattr(module.uvicorn, "run", lambda application, **kwargs: uvicorn_calls.append(kwargs))

    module.main()

    assert len(uvicorn_calls) == 1
    assert "ssl_certfile" not in uvicorn_calls[0]
    assert "ssl_keyfile" not in uvicorn_calls[0]


@pytest.mark.parametrize(("module_name", "environment_loader_name"), LAUNCHERS)
def test_launcher_passes_tls_file_paths_to_uvicorn(
    module_name: str,
    environment_loader_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass the configured certificate and private-key paths to Uvicorn."""
    module = importlib.import_module(module_name)
    environment_loader = getattr(module, environment_loader_name)
    monkeypatch.setattr(environment_loader, "load", lambda self, path=None: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-http",
            "--ssl-certfile",
            "/run/tls/server-chain.pem",
            "--ssl-keyfile",
            "/run/tls/server-key.pem",
        ],
    )
    uvicorn_calls: list[dict[str, object]] = []
    monkeypatch.setattr(module.uvicorn, "run", lambda application, **kwargs: uvicorn_calls.append(kwargs))

    module.main()

    assert len(uvicorn_calls) == 1
    assert uvicorn_calls[0]["ssl_certfile"] == Path("/run/tls/server-chain.pem")
    assert uvicorn_calls[0]["ssl_keyfile"] == Path("/run/tls/server-key.pem")


@pytest.mark.parametrize(("module_name", "environment_loader_name"), LAUNCHERS)
@pytest.mark.parametrize(
    "tls_argument",
    (
        ("--ssl-certfile", "/run/tls/server-chain.pem"),
        ("--ssl-keyfile", "/run/tls/server-key.pem"),
    ),
)
def test_launcher_rejects_an_incomplete_tls_pair_before_loading_environment(
    module_name: str,
    environment_loader_name: str,
    tls_argument: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject one-sided TLS configuration before loading service settings."""
    module = importlib.import_module(module_name)
    environment_loader = getattr(module, environment_loader_name)
    loaded_environment: list[bool] = []
    monkeypatch.setattr(environment_loader, "load", lambda self, path=None: loaded_environment.append(True))
    monkeypatch.setattr(sys, "argv", ["agent-http", *tls_argument])
    monkeypatch.setattr(module.uvicorn, "run", lambda application, **kwargs: pytest.fail("Uvicorn must not start"))

    with pytest.raises(SystemExit) as error:
        module.main()

    assert error.value.code == 2
    assert loaded_environment == []
