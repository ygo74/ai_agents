"""Mail consumes MCP authentication and transport settings from server YAML."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.auth.oauth_token_exchange import (
    Rfc8693OAuthOnBehalfOfTokenSource,
)
from ygo74.agent_runtime.domains.auth.tokens import OAuthOnBehalfOfTokenSource
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.configuration.manifests import AgentManifestLoader, SkillManifestLoader
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry

from ai_agent_lab.mail.bootstrap.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.bootstrap.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.domain.policies.security_floor import MailSecurityFloor
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentSettings
from ai_agent_lab.mail.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.infrastructure.mcp.configuration import load_configuration
from ai_agent_lab.mail.infrastructure.mcp.connection import MailMcpConnectionFactory
from ai_agent_lab.mail.infrastructure.mcp.errors import McpBindingError

ROOT = Path(__file__).resolve().parents[2]
SECRET = "fixture-value-not-a-real-key"  # noqa: S105


@pytest.fixture
def directory() -> ConfigurationDirectory:
    return ConfigurationDirectory(ROOT / "config")


@pytest.fixture
def manifest(directory: ConfigurationDirectory) -> AgentManifest:
    skills = SkillManifestLoader(PermissionRegistry(MailPermission.declared()), MailSecurityFloor().build())
    return AgentManifestLoader(directory, skills).load("mail")


def test_skills_select_gmail_http_and_ignore_the_old_environment_selector(manifest, monkeypatch):
    monkeypatch.setenv("MAIL_MCP_SERVER", "gmail-api")
    assert MailToolsProvider.server_for(manifest) == "gmail-http"


@pytest.mark.parametrize("server", [None, "gmail-api"])
def test_missing_or_conflicting_skill_servers_are_refused(manifest, server):
    changed = manifest.skills[0].model_copy(update={"mcp_server": server})
    with pytest.raises(McpBindingError, match=r"mcp_server|one MCP server"):
        MailToolsProvider.server_for(manifest.model_copy(update={"skills": (changed, *manifest.skills[1:])}))


def test_http_yaml_loads_delegated_oauth_configuration(directory):
    configuration = load_configuration(
        directory,
        "gmail-http",
        environment={"MCP_MAIL_OBO_CLIENT_SECRET": SECRET},
    )
    assert configuration.binding.url == "http://127.0.0.1:9100/mcp"
    assert configuration.authentication_mode is McpAuthenticationMode.OAUTH_ON_BEHALF_OF
    assert configuration.delegated_oauth.audience == "mail-mcp"
    assert configuration.delegated_oauth.scopes == ()
    assert configuration.delegated_oauth.token_url.endswith("/protocol/openid-connect/token")
    assert configuration.delegated_oauth.client_id == "mail-agent"
    assert configuration.delegated_oauth.client_secret.get_secret_value() == SECRET
    assert SECRET not in repr(configuration)
    assert configuration.request_timeout_seconds == 30


def test_stdio_yaml_needs_no_http_credentials(directory):
    configuration = load_configuration(directory, "gmail-api", environment={})
    assert configuration.authentication_mode is McpAuthenticationMode.NONE
    assert not configuration.headers


def test_connection_receives_all_yaml_options(tmp_path):
    root = tmp_path / "config"
    (root / "mcp").mkdir(parents=True)
    (root / "mcp" / "custom.yaml").write_text(
        "transport: http\nurl: http://127.0.0.1:9100/mcp\n"
        "capabilities: [list_labels]\ntools: {list_labels: list_labels}\n"
        "request_timeout_seconds: 19\nauthentication_mode: api_key\n"
        "authentication_api_key:\n  header_name: Authorization\n  value: ${AUTH}\n"
        "headers: {X-Agent: mail}\nnetwork: {proxy_url: http://proxy.example.test:8080}\n",
        encoding="utf-8",
    )
    configuration = load_configuration(ConfigurationDirectory(root), "custom", environment={"AUTH": f"Bearer {SECRET}"})
    with patch("ai_agent_lab.mail.infrastructure.mcp.connection.McpConnection") as connection:
        result = MailMcpConnectionFactory().build(configuration)
    assert result is connection.return_value
    assert connection.call_args.kwargs["timeout_seconds"] == 19
    assert connection.call_args.kwargs["auth"] is None
    assert dict(connection.call_args.kwargs["headers"]) == {"Authorization": f"Bearer {SECRET}", "X-Agent": "mail"}
    assert connection.call_args.kwargs["network"].proxy_url == "http://proxy.example.test:8080"


def test_oauth_factory_receives_yaml_configuration(directory):
    configuration = load_configuration(directory, "gmail", environment={"MAIL_MCP_OAUTH_CLIENT_SECRET": SECRET})
    with (
        patch("ai_agent_lab.mail.infrastructure.mcp.connection.McpOAuthProviderFactory") as oauth,
        patch("ai_agent_lab.mail.infrastructure.mcp.connection.McpConnection") as connection,
    ):
        MailMcpConnectionFactory().build(configuration)
    oauth.return_value.build.assert_called_once_with(configuration.binding.url, configuration.oauth)
    assert connection.call_args.kwargs["auth"] is oauth.return_value.build.return_value


def test_connection_passes_delegated_oauth_configuration_to_runtime(tmp_path):
    root = tmp_path / "config"
    (root / "mcp").mkdir(parents=True)
    (root / "mcp" / "obo.yaml").write_text(
        "transport: http\nurl: https://mail.example.test/mcp\n"
        "capabilities: [list_labels]\ntools: {list_labels: list_labels}\n"
        "authentication_mode: oauth_on_behalf_of\n"
        "authentication_oauth_on_behalf_of: {audience: mail-mcp, scopes: [mail.read]}\n",
        encoding="utf-8",
    )
    configuration = load_configuration(ConfigurationDirectory(root), "obo", environment={})
    source = Mock(spec=OAuthOnBehalfOfTokenSource)
    with patch("ai_agent_lab.mail.infrastructure.mcp.connection.McpConnection") as connection:
        MailMcpConnectionFactory().build(configuration, delegated_token_source=source)

    assert connection.call_args.kwargs["delegated_oauth"] == configuration.delegated_oauth
    assert connection.call_args.kwargs["delegated_token_source"] is source


def test_connection_rejects_missing_delegated_oauth_settings(directory):
    configuration = load_configuration(
        directory,
        "gmail-http",
        environment={"MCP_MAIL_OBO_CLIENT_SECRET": SECRET},
    )
    configuration = replace(configuration, delegated_oauth=None)

    with pytest.raises(McpBindingError, match="missing delegated OAuth settings"):
        MailMcpConnectionFactory().build(configuration)


def test_provider_uses_yaml_not_legacy_environment_settings(directory, manifest, monkeypatch):
    monkeypatch.setenv("MAIL_MCP_SERVER", "gmail-api")
    monkeypatch.setenv("MAIL_MCP_REQUEST_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("MAIL_MCP_AUTH_SCHEME", "api_key")
    monkeypatch.setenv("MAIL_MCP_HTTP_AUTHORIZATION", "unused-legacy-value")
    monkeypatch.setenv("MCP_MAIL_OBO_CLIENT_SECRET", SECRET)
    dialects = Mock()
    source = Mock(spec=OAuthOnBehalfOfTokenSource)
    provider = MailToolsProvider(
        MailAgentSettings(mode="mcp"),
        MailDatasetLoader(),
        manifest=manifest,
        server=MailToolsProvider.server_for(manifest),
        delegated_token_source=source,
        dialects=dialects,
    )
    assert provider.build(base_path=ROOT) is dialects.build.return_value
    binding = dialects.build.call_args.args[0]
    assert binding.server == "gmail-http"
    assert provider._registry is not None
    view = provider._registry.for_skill("search_mail")
    assert view.connection._delegated_token_source is source
    assert provider._registry.server_names == ("gmail-http",)
    assert provider.capabilities(base_path=ROOT) == binding.capabilities


def test_provider_requires_the_yaml_referenced_client_secret(manifest, monkeypatch):
    """The OBO YAML fails clearly when its designated environment secret is absent."""
    monkeypatch.delenv("MCP_MAIL_OBO_CLIENT_SECRET", raising=False)
    provider = MailToolsProvider(
        MailAgentSettings(mode="mcp"),
        MailDatasetLoader(),
        manifest=manifest,
        dialects=Mock(),
    )

    with pytest.raises(McpBindingError, match="MCP_MAIL_OBO_CLIENT_SECRET"):
        provider.build(base_path=ROOT)


def test_provider_builds_source_from_server_yaml_and_environment_secret(manifest, monkeypatch):
    """The default factory receives YAML client settings with only its secret resolved."""
    monkeypatch.setenv("MCP_MAIL_OBO_CLIENT_SECRET", SECRET)
    provider = MailToolsProvider(
        MailAgentSettings(mode="mcp"),
        MailDatasetLoader(),
        manifest=manifest,
        dialects=Mock(),
    )

    provider.build(base_path=ROOT)

    assert provider._registry is not None
    source = provider._registry.for_skill("search_mail").connection._delegated_token_source
    assert source is not None
    assert isinstance(source, Rfc8693OAuthOnBehalfOfTokenSource)
    assert source._settings.token_url.endswith("/protocol/openid-connect/token")
    assert source._settings.client_id == "mail-agent"
    assert source._settings.client_secret.get_secret_value() == SECRET


def test_composition_preserves_an_injected_token_source_for_each_principal():
    """Per-caller composition carries the same host-owned exchange adapter."""
    source = Mock(spec=OAuthOnBehalfOfTokenSource)
    root = MailAgentCompositionRoot(
        MailAgentSettings(mode="mcp"),
        Mock(),
        delegated_token_source=source,
    )

    scoped = root.for_principal(AgentPrincipal(subject="user-123"))

    assert scoped._delegated_token_source is source


@pytest.mark.security
@pytest.mark.parametrize("name", ["../gmail-http", "nested/gmail-http", "..\\gmail-http", "gmail-http."])
def test_server_configuration_names_cannot_escape_the_mcp_directory(directory, name):
    with pytest.raises(McpBindingError, match="unsafe"):
        load_configuration(directory, name, environment={})
