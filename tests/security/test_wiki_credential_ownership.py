"""Keep legacy Wiki credentials bound to their owner through the real MCP registry."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from tests.support.langgraph_fakes import ScriptedChatModel, says
from tests.unit.wiki.test_atlassian_dialect import PAGE
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.configuration.manifests import AgentManifestLoader, SkillManifestLoader
from ygo74.agent_runtime.domains.mcp.binding import McpConnection
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.bootstrap.composition import WikiAgentCompositionRoot
from ai_agent_lab.wiki.bootstrap.wiki_tools_provider import WikiToolsProvider
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.domain.policies.security_floor import WikiSecurityFloor
from ai_agent_lab.wiki.domain.tool_errors import WikiAccessDeniedError
from ai_agent_lab.wiki.infrastructure.configuration.settings import WikiAgentSettings, WikiMcpSettings
from ai_agent_lab.wiki.infrastructure.inmemory.dataset import WikiDatasetLoader
from ai_agent_lab.wiki.infrastructure.mcp.atlassian.client import AtlassianWikiTools
from ai_agent_lab.wiki.infrastructure.mcp.authorization import ConfiguredUserCredentials

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.security


@pytest.fixture
async def legacy_wiki(monkeypatch):
    loader = SkillManifestLoader(PermissionRegistry(WikiPermission.declared()), WikiSecurityFloor().build())
    manifest = AgentManifestLoader(ConfigurationDirectory(ROOT / "config"), loader).load("wiki")
    manifest = manifest.model_copy(update={"mcp_server": "mcp-atlassian-http"})
    read = AsyncMock(return_value={"metadata": PAGE})
    connect = AsyncMock(side_effect=AssertionError("security tests must not connect to MCP"))
    monkeypatch.setattr(AtlassianWikiTools, "_call", read)
    monkeypatch.setattr(McpConnection, "_connect", connect)
    providers = []

    def build(subject, *, scheme="token", credentials=None, manifest_enabled=True):
        provider = WikiToolsProvider(
            WikiAgentSettings(mode="mcp", user_id="diana", _env_file=None),
            WikiDatasetLoader(),
            user_id=subject,
            manifest=manifest if manifest_enabled else None,
            mcp_settings=WikiMcpSettings(
                server="mcp-atlassian-http", auth_scheme=scheme, user_account="diana@example.com",
                user_secret=SecretStr("owner-fixture-token"), _env_file=None,
            ),
            credentials=credentials,
            environment={"WIKI_MCP_READ_ONLY": "true"},
        )
        providers.append(provider)
        return provider

    yield build, read, connect
    for provider in providers:
        await provider.aclose()


@pytest.mark.parametrize("scheme", ["basic", "token", "bearer"])
@pytest.mark.parametrize("manifest_enabled", [True, False])
async def test_fixed_credentials_cannot_be_assigned_to_a_second_subject(legacy_wiki, scheme, manifest_enabled):
    build, read, connect = legacy_wiki
    provider = build("alice", scheme=scheme, manifest_enabled=manifest_enabled)

    with pytest.raises(WikiAccessDeniedError, match="no wiki credential") as failure:
        provider.build(base_path=ROOT)

    assert "owner-fixture-token" not in str(failure.value)
    assert provider._registry is None
    assert provider._connection is None
    read.assert_not_awaited()
    connect.assert_not_awaited()


async def test_owner_read_succeeds_but_saved_adapter_rejects_another_subject(legacy_wiki):
    build, read, connect = legacy_wiki
    provider = build("diana")
    tools = provider.build_for_skill("get_page", base_path=ROOT)
    owner = UserContext(user_id="diana", session_id="owner-session")

    page = await tools.get_page("42", owner)

    assert page.page_id == PAGE["id"]
    adapter = provider._tools_by_server["mcp-atlassian-http"]
    assert not adapter._is_per_user
    assert adapter._account_id == "diana"
    with pytest.raises(WikiAccessDeniedError, match="cannot serve"):
        await tools.get_page("42", UserContext(user_id="alice", session_id="other-session"))
    assert read.await_count == 1
    connect.assert_not_awaited()


async def test_injected_caller_credentials_are_distinct_and_never_use_the_fixed_secret(legacy_wiki):
    build, read, connect = legacy_wiki
    credentials = ConfiguredUserCredentials({
        "diana": ("diana@example.com", SecretStr("diana-fixture-token")),
        "alice": ("alice@example.com", SecretStr("alice-fixture-token")),
    })
    headers = []
    for subject in ("diana", "alice"):
        provider = build(subject, credentials=credentials)
        tools = provider.build_for_skill("get_page", base_path=ROOT)
        await tools.get_page("42", UserContext(user_id=subject, session_id=subject))
        connection = provider._registry.for_skill("get_page").connection
        headers.append(connection._headers["Authorization"])
        assert provider._tools_by_server["mcp-atlassian-http"]._is_per_user

    assert headers == ["Token diana-fixture-token", "Token alice-fixture-token"]
    assert read.await_count == 2
    connect.assert_not_awaited()


async def test_missing_injected_credential_does_not_fall_back_to_deployment_credentials(legacy_wiki):
    build, read, connect = legacy_wiki
    provider = build("alice", credentials=ConfiguredUserCredentials({}))

    with pytest.raises(WikiAccessDeniedError, match="no wiki credential"):
        provider.build_for_skill("summarise_page", base_path=ROOT)

    assert provider._registry is None
    read.assert_not_awaited()
    connect.assert_not_awaited()


def test_explicit_runtime_authentication_does_not_resolve_legacy_credentials(monkeypatch):
    from unittest.mock import Mock

    from ygo74.agent_runtime.domains.mcp.configuration import McpAuthenticationMode
    from ygo74.agent_runtime.domains.mcp.registry import McpAgentRegistryLoader

    from ai_agent_lab.wiki.infrastructure.mcp.configuration import load_configuration
    from ai_agent_lab.wiki.infrastructure.mcp.registry import WikiMcpRegistryLoader

    authorization = Mock(side_effect=AssertionError("legacy credentials must remain unused"))
    loader = WikiMcpRegistryLoader(
        ConfigurationDirectory(ROOT / "config"),
        settings=WikiMcpSettings(_env_file=None),
        user=UserContext(user_id="alice", session_id="runtime-auth"),
        environment={}, authorization=authorization,
    )
    configuration = load_configuration(ConfigurationDirectory(ROOT / "config"), "mcp-atlassian-http", environment={})
    configuration = replace(configuration, authentication_mode=McpAuthenticationMode.API_KEY)
    runtime_connection = Mock(spec=McpConnection)
    create = Mock(return_value=runtime_connection)
    monkeypatch.setattr(McpAgentRegistryLoader, "_create_connection", create)

    assert loader._create_connection(configuration) is runtime_connection
    create.assert_called_once_with(configuration)
    authorization.assert_not_called()


def test_composition_preserves_the_credential_source_when_changing_principal():
    credentials = ConfiguredUserCredentials({})
    root = WikiAgentCompositionRoot(
        WikiAgentSettings(user_id="diana", _env_file=None), ScriptedChatModel([says("ready")]),
        base_path=ROOT, credentials=credentials,
    )

    assert root.for_principal(AgentPrincipal(subject="alice"))._credentials is credentials
