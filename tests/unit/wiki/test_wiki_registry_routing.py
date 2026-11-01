"""Exercise Wiki operation routing through the real registry without opening MCP sessions.

Mirrors ``tests/unit/test_mail_registry_routing.py``: the manifest is loaded for
real and then mutated so that a subset of skills route to a second server,
proving same-server sharing, cross-server routing per operation, alias/capability
scoping, read-only withdrawal, per-user auth and ``aclose()`` idempotence all
hold against the actual :class:`McpAgentRegistryLoader`, not a stand-in for it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import SecretStr
from tests.support.langgraph_fakes import ScriptedChatModel, says
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.configuration.manifests import AgentManifestLoader, SkillManifestLoader
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry

from ai_agent_lab.wiki.application.ports.wiki_tools import WikiTools
from ai_agent_lab.wiki.bootstrap.composition import WikiAgentCompositionRoot
from ai_agent_lab.wiki.bootstrap.skills_factory import WikiSkillsFactory
from ai_agent_lab.wiki.bootstrap.wiki_tools_provider import WikiToolsProvider
from ai_agent_lab.wiki.domain.operation_names import WikiToolName
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.domain.policies.security_floor import WikiSecurityFloor
from ai_agent_lab.wiki.infrastructure.configuration.settings import WikiAgentSettings, WikiMcpSettings
from ai_agent_lab.wiki.infrastructure.inmemory.dataset import WikiDatasetLoader
from ai_agent_lab.wiki.infrastructure.mcp.dialects import create_dialect_registry
from ai_agent_lab.wiki.infrastructure.mcp.errors import McpBindingError

ROOT = Path(__file__).resolve().parents[3]

# Skills deliberately moved onto a second server ("local") so a test can tell
# the two servers' tools apart; everything else stays on the manifest default
# ("mcp-atlassian").
_LOCAL_OVERRIDES = {
    "get_page_children", "list_spaces", "summarise_page", "get_page_history", "update_page", "delete_page"
}


@pytest.fixture
async def routed_backend():
    """Build a real multi-server manifest and a provider wired to fake dialects."""
    loader = SkillManifestLoader(PermissionRegistry(WikiPermission.declared()), WikiSecurityFloor().build())
    manifest = AgentManifestLoader(ConfigurationDirectory(ROOT / "config"), loader).load("wiki")
    skills = tuple(
        skill.model_copy(update={"mcp_server": "wiki-local" if skill.tool_name in _LOCAL_OVERRIDES else None})
        for skill in manifest.skills
    )
    manifest = manifest.model_copy(update={"mcp_server": "mcp-atlassian", "skills": skills})
    delegates: dict[str, AsyncMock] = {}
    connections: dict[str, object] = {}

    def dialect(binding, connection, context):
        delegates[binding.server] = AsyncMock(spec=WikiTools)
        connections[binding.server] = connection
        return delegates[binding.server]

    provider = WikiToolsProvider(
        WikiAgentSettings(mode="mcp", user_id="diana", _env_file=None),
        WikiDatasetLoader(),
        user_id="diana",
        manifest=manifest,
        mcp_settings=WikiMcpSettings(account_id="diana", _env_file=None),
        dialects=create_dialect_registry({"native": dialect, "atlassian": dialect}),
        environment={
            "CONFLUENCE_URL": "https://example.atlassian.net/wiki",
            "CONFLUENCE_USERNAME": "diana@example.com",
            "CONFLUENCE_API_TOKEN": "token",
            "WIKI_MCP_READ_ONLY": "false",
            "WIKI_MCP_TOOLSETS": "confluence",
        },
    )
    yield provider, manifest, delegates, connections
    await provider.aclose()


@pytest.mark.parametrize(
    ("method", "alias", "arguments", "kwargs"),
    [
        ("search", "search_wiki", (Mock(), Mock()), {}),
        ("get_page", "get_page", ("page-1", Mock()), {}),
        ("get_children", "get_page_children", ("page-1", Mock()), {}),
        ("list_spaces", "list_spaces", (Mock(),), {}),
        ("get_comments", "get_comments", ("page-1", Mock()), {}),
        ("create_page", "create_page", ("space", "title", "body", Mock()), {"parent_id": None}),
        ("update_page", "update_page", ("page-1", "body", Mock()), {"title": None, "expected_version": None}),
        ("delete_page", "delete_page", ("page-1", Mock()), {}),
        ("add_comment", "add_comment", ("page-1", "body", Mock()), {"parent_comment_id": None}),
    ],
)
async def test_each_operation_routes_to_its_own_skills_server(routed_backend, method, alias, arguments, kwargs):
    """Every skill resolves its own server, whether shared or distinct."""
    provider, manifest, delegates, connections = routed_backend

    tools = provider.build(base_path=ROOT)
    await getattr(tools, method)(*arguments)

    skill = manifest.skill(alias)
    server = skill.mcp_server or manifest.mcp_server
    getattr(delegates[server], method).assert_awaited_once_with(*arguments, **kwargs)
    assert provider._registry.for_skill(alias).connection is connections[server]
    assert set(provider._registry.server_names) == {"mcp-atlassian", "wiki-local"}


async def test_delivered_manifest_starts_without_unsupported_history(routed_backend, monkeypatch):
    """The default Atlassian deployment assembles without advertising missing aliases."""
    provider, _, _, connections = routed_backend
    loader = SkillManifestLoader(PermissionRegistry(WikiPermission.declared()), WikiSecurityFloor().build())
    provider._manifest = AgentManifestLoader(ConfigurationDirectory(ROOT / "config"), loader).load("wiki")
    monkeypatch.setattr(
        "ai_agent_lab.wiki.bootstrap.composition.WikiToolsProvider", lambda *args, **kwargs: provider
    )
    runtime = WikiAgentCompositionRoot(
        WikiAgentSettings(mode="mcp", user_id="diana"),
        ScriptedChatModel([says("ready")]),
        principal=AgentPrincipal(subject="diana"),
        base_path=ROOT,
    ).build(session_id="default-registry")

    offered = {descriptor.tool_name for descriptor in runtime.registry.skills}
    assert "get_page" in offered
    assert "get_page_history" not in offered
    assert "detect_stale_page" not in offered
    assert set(provider._registry.server_names) == {"mcp-atlassian"}
    await provider.build_for_skill("get_page", base_path=ROOT).get_page("page-1", Mock())
    assert len(connections) == 1
    with pytest.raises(McpBindingError, match="no MCP-enabled skill"):
        provider.build_for_skill("get_page_history", base_path=ROOT)


async def test_sibling_skills_on_the_same_server_share_one_connection(routed_backend):
    """``get_page_children`` and ``list_spaces`` both moved to ``wiki-local``."""
    provider, _, _, connections = routed_backend

    tools_children = provider.build_for_skill("get_page_children", base_path=ROOT)
    tools_spaces = provider.build_for_skill("list_spaces", base_path=ROOT)

    await tools_children.get_children("page-1", Mock())
    await tools_spaces.list_spaces(Mock())

    assert provider._registry.for_skill("get_page_children").connection is connections["wiki-local"]
    assert provider._registry.for_skill("list_spaces").connection is connections["wiki-local"]


async def test_skills_assigned_different_servers_do_not_share_a_connection(routed_backend):
    provider, _, _, connections = routed_backend

    await provider.build_for_skill("get_page", base_path=ROOT).get_page("page-1", Mock())
    await provider.build_for_skill("get_page_children", base_path=ROOT).get_children("page-1", Mock())

    assert connections["mcp-atlassian"] is not connections["wiki-local"]


async def test_a_skill_cannot_invoke_an_operation_its_own_manifest_does_not_declare(routed_backend):
    """A read skill's scoped view rejects a write it never declared, even though its server supports it."""
    provider, _, _, _ = routed_backend

    scoped = provider.build_for_skill("get_page", base_path=ROOT)

    with pytest.raises(McpBindingError, match="does not declare"):
        await scoped.delete_page("page-1", Mock())


async def test_reasoning_skill_keeps_its_own_server_across_every_call_it_makes(routed_backend):
    """``summarise_page`` is a reasoning skill moved onto ``wiki-local``; its own tools object stays scoped there."""
    provider, manifest, delegates, _ = routed_backend

    skills = WikiSkillsFactory(
        tools_for=lambda name: provider.build_for_skill(name, base_path=ROOT),
        reasoner=Mock(),
        manifest=manifest,
        context_builder=Mock(),
        freshness_detector=Mock(),
        runner=Mock(),
    ).build()
    delegates["wiki-local"].get_page.return_value = Mock()
    user = Mock()

    await skills.summary._wiki_tools.get_page("summary-page", user)

    delegates["wiki-local"].get_page.assert_awaited_once_with("summary-page", user)
    delegates["mcp-atlassian"].get_page.assert_not_awaited()


async def test_scoped_tools_cannot_reopen_a_closed_registry(routed_backend):
    provider, _, _, _ = routed_backend
    scoped = provider.build_for_skill("get_page", base_path=ROOT)
    await provider.aclose()

    with pytest.raises(McpBindingError, match="closed"):
        await scoped.get_page("page-1", Mock())
    with pytest.raises(McpBindingError, match="closed"):
        provider.build_for_skill("get_page", base_path=ROOT)


async def test_aclose_is_idempotent(routed_backend):
    provider, _, _, _ = routed_backend
    await provider.build_for_skill("get_page", base_path=ROOT).get_page("page-1", Mock())

    await provider.aclose()
    await provider.aclose()


async def test_a_read_only_deployment_withdraws_write_capabilities(routed_backend):
    """The ``mcp-atlassian`` binding's write tools vanish once the server runs read-only."""
    provider, _, _, _ = routed_backend

    writable = provider.capabilities_for("create_page", base_path=ROOT)
    assert WikiToolName.CREATE_PAGE in writable

    provider._environment = dict(provider._environment) | {"WIKI_MCP_READ_ONLY": "true"}
    provider._configurations.clear()
    read_only = provider.capabilities_for("create_page", base_path=ROOT)
    assert WikiToolName.CREATE_PAGE not in read_only


async def test_caller_identity_is_preserved_per_connection(routed_backend):
    """Wiki's legacy per-user header scheme still identifies the caller on a ``NONE``-auth server."""
    provider, _, _, _ = routed_backend

    captured: list[object] = []
    original_build = provider._dialects.build

    def spying_build(binding, connection, context):
        captured.append(context)
        return original_build(binding, connection, context)

    provider._dialects.build = spying_build  # type: ignore[method-assign]
    await provider.build_for_skill("get_page", base_path=ROOT).get_page("page-1", Mock())

    assert captured, "dialect factory was never invoked"
    assert isinstance(captured[0].is_per_user, bool)
    assert captured[0].account_id


async def test_capability_exposure_does_not_borrow_another_skills_server():
    """A read-only server's scoped capabilities never leak into a skill routed elsewhere."""
    from ai_agent_lab.wiki.bootstrap.composition import WikiAgentCompositionRoot

    descriptors = (Mock(tool_name="summarise_page"), Mock(tool_name="get_page"))
    served = {"summarise_page": frozenset(), "get_page": frozenset({WikiToolName.GET_PAGE})}
    exposed = tuple(
        descriptor
        for descriptor in descriptors
        if WikiAgentCompositionRoot._is_serviceable(descriptor, served)
    )
    assert exposed == (descriptors[1],)


async def test_grouped_authoring_uses_each_operations_own_read_and_write_scope(routed_backend):
    provider, manifest, delegates, _ = routed_backend
    skills = WikiSkillsFactory(
        tools_for=lambda name: provider.build_for_skill(name, base_path=ROOT),
        reasoner=Mock(),
        manifest=manifest,
        context_builder=Mock(),
        freshness_detector=Mock(),
        runner=Mock(),
    ).build()
    user = Mock()
    await skills.authoring._create_tools.create_page("space", "title", "body", user)
    await skills.authoring._update_tools.get_page("page", user)
    await skills.authoring._update_tools.update_page("page", "body", user)
    await skills.authoring._delete_tools.get_page("page", user)
    await skills.authoring._delete_tools.delete_page("page", user)

    delegates["mcp-atlassian"].create_page.assert_awaited_once_with("space", "title", "body", user, parent_id=None)
    delegates["wiki-local"].get_page.assert_any_await("page", user)
    assert delegates["wiki-local"].get_page.await_count == 2
    delegates["wiki-local"].update_page.assert_awaited_once_with(
        "page", "body", user, title=None, expected_version=None
    )
    delegates["wiki-local"].delete_page.assert_awaited_once_with("page", user)


async def test_grouped_search_uses_each_standalone_reads_own_scope(routed_backend):
    """CR-002: ``DocumentationSearchSkill`` routes each standalone read through its own manifest skill."""
    provider, manifest, delegates, _ = routed_backend
    skills = WikiSkillsFactory(
        tools_for=lambda name: provider.build_for_skill(name, base_path=ROOT),
        reasoner=Mock(),
        manifest=manifest,
        context_builder=Mock(),
        freshness_detector=Mock(),
        runner=Mock(),
    ).build()
    user = Mock()

    await skills.search.search(Mock(is_empty=False), user)
    await skills.search.get_page("page-1", user)
    await skills.search.get_children("page-1", user)
    await skills.search.list_spaces(user)

    delegates["mcp-atlassian"].search.assert_awaited_once()
    delegates["mcp-atlassian"].get_page.assert_awaited_once_with("page-1", user)
    delegates["wiki-local"].get_children.assert_awaited_once_with("page-1", user)
    delegates["wiki-local"].list_spaces.assert_awaited_once_with(user)


async def test_grouped_search_uses_one_server_when_the_manifest_declares_one(routed_backend):
    """CR-002: a single-server manifest still routes every standalone read through its own skill alias."""
    provider, manifest, delegates, _ = routed_backend
    single_server_manifest = manifest.model_copy(
        update={"skills": tuple(skill.model_copy(update={"mcp_server": None}) for skill in manifest.skills)}
    )
    provider._manifest = single_server_manifest
    skills = WikiSkillsFactory(
        tools_for=lambda name: provider.build_for_skill(name, base_path=ROOT),
        reasoner=Mock(),
        manifest=single_server_manifest,
        context_builder=Mock(),
        freshness_detector=Mock(),
        runner=Mock(),
    ).build()
    user = Mock()

    await skills.search.search(Mock(is_empty=False), user)
    await skills.search.get_page("page-1", user)
    await skills.search.get_children("page-1", user)
    await skills.search.list_spaces(user)

    delegates["mcp-atlassian"].search.assert_awaited_once()
    delegates["mcp-atlassian"].get_page.assert_awaited_once_with("page-1", user)
    delegates["mcp-atlassian"].get_children.assert_awaited_once_with("page-1", user)
    delegates["mcp-atlassian"].list_spaces.assert_awaited_once_with(user)
    assert set(provider._registry.server_names) == {"mcp-atlassian"}


async def test_a_missing_read_skill_fails_lazily_through_the_shared_router(routed_backend):
    """CR-004: a manifest-absent read still assembles, and fails on first use with no new upstream connection."""
    provider, manifest, delegates, connections = routed_backend
    withdrawn_manifest = manifest.model_copy(
        update={"skills": tuple(skill for skill in manifest.skills if skill.tool_name != "get_page_history")}
    )
    skills = WikiSkillsFactory(
        tools_for=lambda name: provider.build_for_skill(name, base_path=ROOT),
        reasoner=Mock(),
        manifest=withdrawn_manifest,
        context_builder=Mock(),
        freshness_detector=Mock(),
        runner=Mock(),
    ).build()
    connections_before_invocation = dict(connections)

    with pytest.raises(McpBindingError, match="not configured in this deployment's manifest"):
        await skills.search.get_history("page-1", Mock())

    assert connections == connections_before_invocation
    for delegate in delegates.values():
        delegate.get_history.assert_not_awaited()


async def test_a_missing_write_skill_fails_lazily_through_the_shared_router(routed_backend):
    """CR-004: a manifest-absent write skill assembles and fails the same way as a missing read."""
    provider, manifest, delegates, connections = routed_backend
    withdrawn_manifest = manifest.model_copy(
        update={"skills": tuple(skill for skill in manifest.skills if skill.tool_name != "delete_page")}
    )
    skills = WikiSkillsFactory(
        tools_for=lambda name: provider.build_for_skill(name, base_path=ROOT),
        reasoner=Mock(),
        manifest=withdrawn_manifest,
        context_builder=Mock(),
        freshness_detector=Mock(),
        runner=Mock(),
    ).build()
    connections_before_invocation = dict(connections)

    with pytest.raises(McpBindingError, match="not configured in this deployment's manifest"):
        await skills.authoring._delete_tools.delete_page("page-1", Mock())

    assert connections == connections_before_invocation
    for delegate in delegates.values():
        delegate.delete_page.assert_not_awaited()


async def test_registry_connections_receive_resolved_stdio_values(routed_backend):
    provider, _, _, _ = routed_backend
    provider.build(base_path=ROOT)
    connection = provider._registry.for_skill("get_page").connection
    assert connection._binding.env["CONFLUENCE_URL"] == provider._environment["CONFLUENCE_URL"]
    assert connection._binding.env["CONFLUENCE_API_TOKEN"] == provider._environment["CONFLUENCE_API_TOKEN"]


async def test_registry_connections_preserve_legacy_caller_headers_and_timeout(routed_backend):
    provider, _, _, _ = routed_backend
    provider._mcp_settings = WikiMcpSettings(
        auth_scheme="bearer", user_account="diana", user_secret=SecretStr("fixture-token"), timeout_seconds=61
    )
    provider.build(base_path=ROOT)
    connection = provider._registry.for_skill("summarise_page").connection
    assert connection._headers["Authorization"] == "Bearer fixture-token"
    assert connection._timeout == 61


async def test_capabilities_are_limited_to_the_selected_skills_aliases(routed_backend):
    provider, _, _, _ = routed_backend
    assert provider.capabilities_for("get_page", base_path=ROOT) == {WikiToolName.GET_PAGE}
    assert provider.capabilities_for("summarise_page", base_path=ROOT) == {
        WikiToolName.GET_PAGE, WikiToolName.GET_COMMENTS, WikiToolName.GET_PAGE_CHILDREN
    }
