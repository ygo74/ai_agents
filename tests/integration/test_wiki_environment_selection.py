"""Wiki launchers load the chosen environment before application settings."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, Mock

import pytest

from ai_agent_lab.wiki.adapters.cli import entrypoint
from ai_agent_lab.wiki.adapters.http import server as http_server
from ai_agent_lab.wiki.infrastructure.configuration.environment import (
    ENV_FILE_VARIABLE,
    WikiEnvironmentFile,
)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Avoid inheriting developer configuration in launcher tests."""
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.chdir(tmp_path)
    for name in (
        ENV_FILE_VARIABLE,
        "WIKI_AGENT_MODE",
        "WIKI_AGENT_USER_ID",
        "WIKI_AGENT_HTTP_API_KEY",
        "WIKI_AGENT_HTTP_OIDC_ISSUER",
    ):
        monkeypatch.delenv(name, raising=False)


def test_selected_environment_file_is_loaded_without_overriding_process(tmp_path, monkeypatch):
    """The explicit file supplies settings but cannot override the process."""
    selected = tmp_path / "wiki.env"
    selected.write_text("WIKI_AGENT_USER_ID=from-file\n", encoding="utf-8")
    monkeypatch.setenv("WIKI_AGENT_MODE", "mock")
    monkeypatch.setenv("WIKI_AGENT_USER_ID", "from-process")

    WikiEnvironmentFile().load(selected)

    assert os.environ["WIKI_AGENT_USER_ID"] == "from-process"
    assert os.environ[ENV_FILE_VARIABLE] == str(selected.resolve())


def test_missing_explicit_environment_file_fails(tmp_path):
    """A typo in an explicitly selected file fails before agent startup."""
    with pytest.raises(FileNotFoundError, match="Wiki environment file does not exist"):
        WikiEnvironmentFile().load(tmp_path / "missing.env")


def test_http_launcher_preserves_selected_file_for_reload(tmp_path, monkeypatch):
    """The HTTP launcher loads the selected file before Uvicorn starts."""
    selected = tmp_path / "wiki.env"
    selected.write_text("WIKI_AGENT_HTTP_API_KEY=fixture-key\n", encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(http_server.uvicorn, "run", run)
    monkeypatch.setattr(
        "sys.argv", ["wiki-http", "--env-file", "wiki.env", "--port", "8124", "--reload"]
    )

    http_server.main()

    run.assert_called_once_with(
        "ai_agent_lab.wiki.bootstrap.service:build_app",
        factory=True,
        host="127.0.0.1",
        port=8124,
        reload=True,
    )
    assert os.environ[ENV_FILE_VARIABLE] == str(selected.resolve())
    assert os.environ["WIKI_AGENT_HTTP_API_KEY"] == "fixture-key"


def test_cli_argument_is_forwarded_before_build(monkeypatch, tmp_path):
    """The console command accepts and forwards an environment-file path."""
    selected = tmp_path / "wiki.env"
    selected.write_text("WIKI_AGENT_MODE=mock\n", encoding="utf-8")
    cli = Mock()
    cli.run = AsyncMock()
    build = Mock(return_value=cli)
    monkeypatch.setattr(entrypoint, "build_cli", build)
    monkeypatch.setattr("sys.argv", ["wiki-agent", "--env-file", str(selected)])

    entrypoint.main()

    build.assert_called_once_with(log_level=None, env_file=selected)
    cli.run.assert_awaited_once()
