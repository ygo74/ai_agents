"""Exercise YAML-configured Mail over authenticated HTTP without a real mailbox."""

import asyncio
import json
import re
import shutil
import socket
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import uvicorn
import yaml
from tests.support.maf_fakes import ScriptedChatClient, says
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode
from ygo74.agent_runtime.domains.mcpserver.host import McpServerHost
from ygo74.agent_runtime.domains.mcpserver.http_binding import HEALTH_PATH, McpHttpBinding

from ai_agent_lab.mail.adapters.cli.authorise import MailAuthorisation
from ai_agent_lab.mail.adapters.cli.discover import ToolDiscovery
from ai_agent_lab.mail.bootstrap.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentSettings
from ai_agent_lab.mail.infrastructure.mcp.configuration import load_configuration
from mail_mcp.gmail import server as gmail_server
from mail_mcp.protocol.authentication import MailMcpAuthentication
from mail_mcp.protocol.serving import MailToolSurface
from mail_mcp.reference.mailbox import MailboxDatasetLoader
from mail_mcp.reference.server import DatasetDirectory

ROOT = Path(__file__).resolve().parents[2]
SECRET = "fixture-http-credential"  # noqa: S105


def test_gmail_http_debug_configuration_launches_the_matching_authenticated_endpoint(monkeypatch):
    source = (ROOT / ".vscode" / "launch.json").read_text(encoding="utf-8")
    launch = json.loads(re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE))
    debug = next(item for item in launch["configurations"] if item["name"] == "Mail MCP Gmail - HTTP")
    owner_input = next(item for item in launch["inputs"] if item["id"] == "mailMcpOwner")
    configuration = load_configuration(
        ConfigurationDirectory(ROOT / "config"),
        "gmail-http",
        environment={"MAIL_AGENT_MCP_OBO_CLIENT_SECRET": "test-client-secret"},
    )
    assert debug["module"] == "mail_mcp.gmail.server"
    assert "envFile" not in debug
    assert debug["args"][:2] == ["--env-file", "${input:mailMcpEnvFile}"]
    assert debug["args"][-2:] == ["--log-level", "${input:mailMcpLogLevel}"]
    assert "default" not in owner_input
    assert "Keycloak user sub" in owner_input["description"]
    assert debug["justMyCode"] is False
    assert "MAIL_MCP_AUTH_MODE" not in debug["env"]
    assert configuration.authentication_mode is McpAuthenticationMode.OAUTH_ON_BEHALF_OF
    assert configuration.delegated_oauth.audience == "mail-mcp"
    assert configuration.binding.url == "http://127.0.0.1:9100/mcp"

    surface = Mock()
    build = Mock(return_value=surface)
    monkeypatch.setattr(gmail_server, "build_surface", build)
    monkeypatch.setattr(gmail_server.EnvironmentFile, "load", lambda self: None)
    monkeypatch.setenv("MAIL_MCP_AUTH_MODE", "jwt")
    monkeypatch.setenv("MAIL_MCP_OIDC_ISSUER", "https://keycloak.example.test/realms/test")
    monkeypatch.setenv("MAIL_MCP_OIDC_AUDIENCE", "mail-mcp")
    monkeypatch.setenv("MAIL_MCP_RESOURCE_URL", configuration.binding.url)
    inputs = {
        "${input:mailMcpEnvFile}": ".env",
        "${input:mailMcpOwner}": "keycloak-user-sub",
        "${input:mailMcpLogLevel}": "debug",
    }
    arguments = [inputs.get(arg, arg) for arg in debug["args"]]
    monkeypatch.setattr("sys.argv", ["mail_mcp.gmail.server", *arguments])
    gmail_server.main()

    build.assert_called_once_with("keycloak-user-sub", host="127.0.0.1", port=9100)
    authentication = surface.run_http.call_args.args[0]
    assert authentication.resource_url == configuration.binding.url
    assert surface.run_http.call_args.kwargs["log_level"] == "debug"


@pytest.mark.security
async def test_agent_discovery_and_authorisation_use_yaml_over_authenticated_http(tmp_path, monkeypatch):
    root = tmp_path / "config"
    shutil.copytree(ROOT / "config", root)
    monkeypatch.setenv("YGO74_AGENT_RUNTIME_CONFIG_DIR", str(root))
    monkeypatch.setenv("MAIL_MCP_HTTP_AUTHORIZATION", f"Bearer {SECRET}")
    monkeypatch.setenv("MAIL_MCP_SERVER", "gmail-api")

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.listen()
    path = root / "mcp" / "gmail-http.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["url"] = f"http://127.0.0.1:{port}/mcp"
    document["authentication_mode"] = "api_key"
    document.pop("authentication_oauth_on_behalf_of")
    document["authentication_api_key"] = {
        "header_name": "Authorization",
        "value": "${MAIL_MCP_HTTP_AUTHORIZATION}",
    }
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    dataset = MailboxDatasetLoader().load(ROOT / "data" / "mail" / "sample_mailbox.json")
    surface = MailToolSurface(DatasetDirectory(dataset), name="mail-http-fixture", host="127.0.0.1", port=port)
    authentication = MailMcpAuthentication.from_environment(
        {"MAIL_MCP_AUTH_MODE": "api_key", "MAIL_MCP_HTTP_TOKEN": SECRET}
    )
    application = McpServerHost(
        policy=authentication.policy, binding=McpHttpBinding(host="127.0.0.1", port=port)
    ).application(surface.server.streamable_http_app())
    server = uvicorn.Server(uvicorn.Config(application, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    runtime = None
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    pytest.fail("HTTP fixture exited before becoming ready")
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient() as client:
            health = await client.get(f"http://127.0.0.1:{port}{HEALTH_PATH}")
            assert health.status_code == 200
            refusal = await client.post(document["url"], json={})
            assert refusal.status_code == 401

        runtime = MailAgentCompositionRoot(
            MailAgentSettings(mode="mcp"),
            ScriptedChatClient([says("ready")]),
            base_path=ROOT,
        ).build(session_id="yaml-http-test")
        assert await runtime.mail_tools.list_labels(runtime.user)
        configuration = load_configuration(ConfigurationDirectory(root), "gmail-http")
        discovered = await ToolDiscovery(configuration).run()
        assert discovered["server"] == "gmail-http"
        assert "search_mail" in {tool["name"] for tool in discovered["tools"]}
        labels, scopes = await MailAuthorisation("gmail-http").run()
        assert labels > 0
        assert "not applicable" in scopes
    finally:
        if runtime is not None:
            await runtime.aclose()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        listener.close()
