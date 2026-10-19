"""Component launchers load exactly the selected file, without credential mixing."""

import json
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from tests.support.maf_fakes import ScriptedChatClient, says
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory

from ai_agent_lab.mail.adapters.cli import authorise, discover, entrypoint
from ai_agent_lab.mail.adapters.http import server as http_server
from ai_agent_lab.mail.bootstrap import service
from ai_agent_lab.mail.infrastructure.configuration.environment import ENV_FILE_VARIABLE, MailEnvironmentFile
from ai_agent_lab.mail.infrastructure.configuration.settings import ChatClientSettings, MailAgentSettings
from ai_agent_lab.mail.infrastructure.mcp.configuration import load_configuration
from mail_mcp.gmail import authorise as gmail_authorise
from mail_mcp.gmail import server as gmail_server
from mail_mcp.gmail.credentials import GmailCredentialSettings
from mail_mcp.gmail.environment import EnvironmentFile

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.chdir(tmp_path)
    for name in (
        ENV_FILE_VARIABLE,
        "MAIL_AGENT_USER_ID",
        "MAIL_AGENT_USER_EMAIL",
        "MAIL_AGENT_HTTP_API_KEY",
        "MAIL_AGENT_HTTP_OIDC_ISSUER",
        "MAIL_MCP_HTTP_AUTHORIZATION",
        "MAIL_MCP_HTTP_TOKEN",
        "MAIL_MCP_AUTH_MODE",
        "GMAIL_OAUTH_CLIENT_ID",
        "GMAIL_OAUTH_CLIENT_SECRET",
        "OPENAI_CHAT_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("loader", [MailEnvironmentFile, EnvironmentFile])
def test_default_file_and_process_precedence(loader, tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("MAIL_AGENT_USER_ID=from-default\n", encoding="utf-8")
    monkeypatch.setenv("MAIL_AGENT_USER_ID", "from-process")
    loader().load()
    assert os.environ["MAIL_AGENT_USER_ID"] == "from-process"
    monkeypatch.delenv("MAIL_AGENT_USER_ID")
    loader().load()
    assert os.environ["MAIL_AGENT_USER_ID"] == "from-default"


@pytest.mark.parametrize("loader", [MailEnvironmentFile, EnvironmentFile])
def test_missing_default_is_optional_but_explicit_file_is_required(loader, tmp_path):
    loader().load()
    with pytest.raises(FileNotFoundError, match="does not exist"):
        if loader is EnvironmentFile:
            loader(tmp_path / "missing.env").load()
        else:
            loader().load(tmp_path / "missing.env")


async def test_console_uses_selected_file_through_settings_chat_and_yaml(tmp_path):
    (tmp_path / ".env").write_text(
        "MAIL_AGENT_USER_EMAIL=wrong@example.com\nOPENAI_CHAT_MODEL=wrong-model\n"
        "MCP_MAIL_OBO_CLIENT_SECRET=wrong-secret\n",
        encoding="utf-8",
    )
    selected = tmp_path / "mail agent.env"
    selected.write_text(
        "MAIL_AGENT_USER_ID=selected-user\nOPENAI_CHAT_MODEL=selected-model\n"
        "MCP_MAIL_OBO_CLIENT_SECRET=fixture-secret\n",
        encoding="utf-8",
    )
    client = ScriptedChatClient([says("ready")])
    cli = entrypoint.build_cli(base_path=ROOT, chat_client=client, env_file=selected)
    try:
        assert cli._runtime.user.user_id == "selected-user"
        assert MailAgentSettings().user_email == "local-user@example.com"
        assert ChatClientSettings().openai_model == "selected-model"
        configuration = load_configuration(ConfigurationDirectory(ROOT / "config"), "gmail-http")
        assert configuration.delegated_oauth.client_secret.get_secret_value() == "fixture-secret"
        assert os.environ[ENV_FILE_VARIABLE] == str(selected.resolve())
    finally:
        await cli._runtime.aclose()


def test_console_argument_is_forwarded_before_build(monkeypatch, tmp_path):
    selected = tmp_path / "mail.env"
    cli = Mock()
    cli.run = AsyncMock()
    build = Mock(return_value=cli)
    monkeypatch.setattr(entrypoint, "build_cli", build)
    monkeypatch.setattr("sys.argv", ["mail-agent", "--env-file", str(selected)])
    entrypoint.main()
    build.assert_called_once_with(env_file=selected)
    cli.run.assert_awaited_once()


def test_http_launcher_preserves_selected_file_for_reload(tmp_path, monkeypatch):
    selected = tmp_path / "http.env"
    selected.write_text("MAIL_AGENT_HTTP_API_KEY=fixture-key\n", encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(http_server.uvicorn, "run", run)
    monkeypatch.setattr(
        "sys.argv", ["mail-http", "--env-file", "http.env", "--port", "8123", "--reload"]
    )
    http_server.main()
    run.assert_called_once_with(
        "ai_agent_lab.mail.bootstrap.service:build_app",
        factory=True,
        host="127.0.0.1",
        port=8123,
        reload=True,
    )
    assert os.environ[ENV_FILE_VARIABLE] == str(selected.resolve())
    monkeypatch.delenv("MAIL_AGENT_HTTP_API_KEY")
    MailEnvironmentFile().load()
    assert os.environ["MAIL_AGENT_HTTP_API_KEY"] == "fixture-key"


def test_http_factory_uses_selected_file_not_default(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("MAIL_AGENT_HTTP_OIDC_ISSUER=https://wrong.invalid\n", encoding="utf-8")
    selected = tmp_path / "http.env"
    selected.write_text("MAIL_AGENT_HTTP_API_KEY=fixture-key\n", encoding="utf-8")
    monkeypatch.setattr(
        service.MailAgentApplicationFactory,
        "build_chat_client",
        lambda self: ScriptedChatClient([says("ready")]),
    )
    app = service.build_app(base_path=ROOT, env_file=selected)
    assert app.state.conversations is not None
    assert "MAIL_AGENT_HTTP_OIDC_ISSUER" not in os.environ


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
def test_gmail_server_loads_own_file_before_credentials_and_authentication(tmp_path, monkeypatch, transport):
    (tmp_path / ".env").write_text("GMAIL_OAUTH_CLIENT_SECRET=wrong-secret\n", encoding="utf-8")
    selected = tmp_path / "gmail.env"
    selected.write_text(
        "GMAIL_OAUTH_CLIENT_ID=server-client\nMAIL_MCP_AUTH_MODE=api_key\n"
        "MAIL_MCP_HTTP_TOKEN=fixture-secret\n",
        encoding="utf-8",
    )
    surface = Mock()
    monkeypatch.setattr(gmail_server, "build_surface", Mock(return_value=surface))
    monkeypatch.setattr(
        "sys.argv", ["gmail-server", "--env-file", str(selected), "--transport", transport]
    )
    gmail_server.main()
    assert GmailCredentialSettings().client_id == "server-client"
    assert GmailCredentialSettings().client_secret.get_secret_value() == ""
    if transport == "stdio":
        surface.run.assert_called_once()
    else:
        surface.run_http.assert_called_once()
        authentication = surface.run_http.call_args.args[0]
        context = authentication.policy.build().authenticate({"authorization": "Bearer fixture-secret"})
        assert context.identity.user_id == "mail-agent"


@pytest.mark.parametrize("utility", ["agent-authorise", "discovery", "gmail-authorise"])
def test_utilities_load_selected_component_file(tmp_path, monkeypatch, utility):
    selected = tmp_path / "utility.env"
    selected.write_text(
        "MAIL_MCP_HTTP_AUTHORIZATION=fixture-header\n"
        "GMAIL_OAUTH_CLIENT_ID=fixture-client\nGMAIL_OAUTH_CLIENT_SECRET=fixture-secret\n"
        "MCP_MAIL_OBO_CLIENT_SECRET=fixture-secret\n",
        encoding="utf-8",
    )
    arguments = ["utility", "--env-file", str(selected)]
    monkeypatch.setenv("YGO74_AGENT_RUNTIME_CONFIG_DIR", str(ROOT / "config"))
    if utility == "agent-authorise":
        monkeypatch.setattr(authorise.MailAuthorisation, "run", AsyncMock(return_value=(1, "not applicable")))
        arguments.extend(["--server", "gmail-http"])
        launch = authorise.main
    elif utility == "discovery":
        monkeypatch.setattr(discover.ToolDiscovery, "run", AsyncMock(return_value={"tools": []}))
        arguments.extend(["--server", "gmail-http"])
        launch = discover.main
    else:
        monkeypatch.setattr(gmail_authorise.GmailConsent, "run", AsyncMock(return_value=(1, "fixture-scope")))
        launch = gmail_authorise.main
    monkeypatch.setattr("sys.argv", arguments)
    launch()
    assert os.environ["GMAIL_OAUTH_CLIENT_ID"] == "fixture-client"
    assert os.environ["MAIL_MCP_HTTP_AUTHORIZATION"] == "fixture-header"


def test_mail_debug_profiles_pass_component_selection_without_preloading_default():
    source = (ROOT / ".vscode" / "launch.json").read_text(encoding="utf-8")
    launch = json.loads(re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE))
    inputs = {item["id"]: item for item in launch["inputs"]}
    assert inputs["mailAgentEnvFile"]["default"] == ".env_mail_agent_http"
    assert inputs["mailMcpEnvFile"]["default"] == ".env_mcp_server"
    profiles = [
        item for item in launch["configurations"]
        if item["module"].startswith(("ai_agent_lab.mail.", "mail_mcp.gmail."))
    ]
    assert len(profiles) == 7
    for profile in profiles:
        selection = "mailMcpEnvFile" if profile["module"].startswith("mail_mcp.") else "mailAgentEnvFile"
        assert profile["args"][:2] == ["--env-file", f"${{input:{selection}}}"]
        assert "envFile" not in profile
