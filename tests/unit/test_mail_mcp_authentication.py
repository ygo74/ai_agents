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
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest, SkillManifest
from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode
from ygo74.agent_runtime.domains.security.operations import OperationType, RiskLevel, ToolOperationDescriptor
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry

from ai_agent_lab.mail.bootstrap.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.bootstrap.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.domain.operation_names import MailToolName
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


def test_server_for_reports_the_agent_default_server(manifest, monkeypatch):
    monkeypatch.setenv("MAIL_MCP_SERVER", "gmail-api")
    assert MailToolsProvider.server_for(manifest) == "gmail-http"


def test_server_for_falls_back_to_a_skill_override_when_no_agent_default(manifest):
    changed = manifest.skills[0].model_copy(update={"mcp_server": "gmail-api"})
    selected = manifest.model_copy(update={"mcp_server": None, "skills": (changed, *manifest.skills[1:])})
    assert MailToolsProvider.server_for(selected) == "gmail-api"


def test_server_for_refuses_when_no_server_is_declared_anywhere(manifest):
    changed = manifest.skills[0].model_copy(update={"mcp_server": None})
    selected = manifest.model_copy(update={"mcp_server": None, "skills": (changed, *manifest.skills[1:])})
    with pytest.raises(McpBindingError, match="mcp_server"):
        MailToolsProvider.server_for(selected)


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
    provider.build(base_path=ROOT)
    tools = provider.build_for_skill("search_mail", base_path=ROOT)
    assert tools._delegate is dialects.build.return_value
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


def _skill(tool_name: str, *, mcp_server: str | None, mcp_tools: tuple[str, ...] = ()) -> SkillManifest:
    """Build one minimal, valid skill manifest for the registry tests below."""
    return SkillManifest(
        tool_name=tool_name,
        implementation=f"mail.{tool_name}",
        description="fixture capability",
        operation=ToolOperationDescriptor(
            tool_name=tool_name,
            operation_type=OperationType.READ,
            risk_level=RiskLevel.LOW,
            required_permission=MailPermission.READ,
            confirmation_required_by_default=False,
        ),
        mcp_server=mcp_server,
        mcp_tools=mcp_tools,
    )


def _two_server_manifest() -> AgentManifest:
    """An agent whose skills are deliberately routed to two distinct real servers.

    ``gmail-api`` and ``local`` are both unauthenticated stdio bindings already
    delivered under ``config/mcp``, so resolving their capabilities needs no
    secret and opens no connection - exactly what these tests must stay free of.
    """
    return AgentManifest(
        name="mail-multiserver-fixture",
        description="fixture",
        instructions="fixture",
        mcp_server=None,
        skills=(
            _skill("search_mail", mcp_server="gmail-api", mcp_tools=("search_mail",)),
            _skill("get_mail", mcp_server="gmail-api", mcp_tools=("get_mail",)),
            _skill("send_mail", mcp_server="local", mcp_tools=("create_draft", "send_mail")),
        ),
    )


class TestMultiServerRegistryRouting:
    """Per-skill routing against a fabricated agent spanning two real servers."""

    def test_skills_on_the_same_server_share_one_connection(self):
        manifest = _two_server_manifest()
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)

        search_tools = provider.build_for_skill("search_mail", base_path=ROOT)
        get_tools = provider.build_for_skill("get_mail", base_path=ROOT)

        assert search_tools is not get_tools  # distinct per-skill scoped views ...
        assert search_tools._delegate is get_tools._delegate  # ... of the same shared dialect object
        assert provider._registry.server_names == ("gmail-api", "local")

    def test_a_skill_on_a_different_server_gets_its_own_connection(self):
        manifest = _two_server_manifest()
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)

        search_tools = provider.build_for_skill("search_mail", base_path=ROOT)
        send_tools = provider.build_for_skill("send_mail", base_path=ROOT)

        assert search_tools._delegate is not send_tools._delegate
        view_search = provider._registry.for_skill("search_mail")
        view_send = provider._registry.for_skill("send_mail")
        assert view_search.connection is not view_send.connection
        assert view_search.server_name == "gmail-api"
        assert view_send.server_name == "local"

    def test_a_restricted_alias_is_refused_explicitly(self):
        """A skill cannot resolve a tool outside the aliases its manifest declared."""
        manifest = _two_server_manifest()
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)
        provider.build_for_skill("search_mail", base_path=ROOT)

        view = provider._registry.for_skill("search_mail")
        with pytest.raises(McpBindingError, match="does not allow MCP tool alias"):
            view.remote_tool("send_mail")

    async def test_a_skill_level_scoped_view_refuses_an_operation_outside_its_own_aliases(self):
        """The production ``build_for_skill`` path itself refuses out-of-scope calls.

        ``search_mail`` only declares ``search_mail`` in its manifest, so even
        though it shares the ``gmail-api`` server (and its dialect object)
        with ``get_mail``, calling ``get_message`` through its own resolved
        tools must fail explicitly rather than silently reaching the server.
        """
        manifest = _two_server_manifest()
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)
        search_tools = provider.build_for_skill("search_mail", base_path=ROOT)

        with pytest.raises(McpBindingError, match="does not declare MCP tool alias"):
            await search_tools.get_message("msg-1", user=Mock())

    def test_capabilities_differ_per_server(self):
        """``gmail-api`` can send and delete labels; ``local`` offers the same full contract."""
        manifest = _two_server_manifest()
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)

        search_capabilities = provider.capabilities_for("search_mail", base_path=ROOT)
        send_capabilities = provider.capabilities_for("send_mail", base_path=ROOT)

        assert search_capabilities == {MailToolName.SEARCH_MAIL}
        assert send_capabilities == {MailToolName.CREATE_DRAFT, MailToolName.SEND_MAIL}
        assert search_capabilities | send_capabilities <= provider.capabilities(base_path=ROOT)

    def test_capabilities_are_read_without_opening_a_connection_or_resolving_oauth_secrets(self, monkeypatch):
        """Reading capabilities for an OAuth-protected server needs no secret.

        ``gmail-http`` requires ``MCP_MAIL_OBO_CLIENT_SECRET`` to open a
        connection; ``capabilities_for``/``capabilities`` must still answer
        without it, because they only read the delivered binding.
        """
        monkeypatch.delenv("MCP_MAIL_OBO_CLIENT_SECRET", raising=False)
        manifest = AgentManifest(
            name="mail-oauth-fixture",
            description="fixture",
            instructions="fixture",
            mcp_server="gmail-http",
            skills=(_skill("search_mail", mcp_server=None, mcp_tools=("search_mail",)),),
        )
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)

        capabilities = provider.capabilities_for("search_mail", base_path=ROOT)

        assert capabilities  # resolved purely from the binding
        assert provider._registry is None  # never built a connection/registry to answer this

    def test_an_unavailable_skill_fails_explicitly_rather_than_falling_back(self):
        """A skill the manifest never declared raises instead of silently reusing another server."""
        manifest = _two_server_manifest()
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)
        provider.build_for_skill("search_mail", base_path=ROOT)

        with pytest.raises(McpBindingError, match="no MCP-enabled skill"):
            provider._registry.for_skill("draft_mail_reply")

    async def test_cleanup_closes_each_connection_once_and_is_idempotent(self):
        manifest = _two_server_manifest()
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)
        provider.build_for_skill("search_mail", base_path=ROOT)
        provider.build_for_skill("send_mail", base_path=ROOT)
        registry = provider._registry
        closed: list[object] = []
        for connection in registry._connections.values():
            original = connection.aclose

            async def _tracked(original=original, connection=connection):
                closed.append(connection)
                await original()

            connection.aclose = _tracked

        await provider.aclose()
        await provider.aclose()  # idempotent: no error, no double-close

        assert len(closed) == 2  # each distinct server connection closed exactly once

    def test_delegated_auth_is_built_per_server_from_its_own_yaml(self, monkeypatch):
        """OAuth-on-behalf-of settings are resolved per server, not globally."""
        monkeypatch.setenv("MCP_MAIL_OBO_CLIENT_SECRET", SECRET)
        manifest = AgentManifest(
            name="mail-auth-fixture",
            description="fixture",
            instructions="fixture",
            mcp_server=None,
            skills=(
                _skill("search_mail", mcp_server="gmail-http", mcp_tools=("search_mail",)),
                _skill("send_mail", mcp_server="local", mcp_tools=("create_draft", "send_mail")),
            ),
        )
        provider = MailToolsProvider(MailAgentSettings(mode="mcp"), MailDatasetLoader(), manifest=manifest)

        provider.build_for_skill("search_mail", base_path=ROOT)
        provider.build_for_skill("send_mail", base_path=ROOT)

        oauth_view = provider._registry.for_skill("search_mail")
        plain_view = provider._registry.for_skill("send_mail")
        assert oauth_view.connection._delegated_token_source is not None
        assert isinstance(oauth_view.connection._delegated_token_source, Rfc8693OAuthOnBehalfOfTokenSource)
        assert plain_view.connection._delegated_token_source is None
