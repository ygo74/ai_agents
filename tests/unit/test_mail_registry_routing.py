"""Exercise operation routing through the real registry without opening MCP sessions."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.configuration.manifests import AgentManifestLoader, SkillManifestLoader
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry

from ai_agent_lab.mail.application.ports.mail_tools import MailTools
from ai_agent_lab.mail.bootstrap.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.bootstrap.skills_factory import MailSkillsFactory
from ai_agent_lab.mail.domain.operation_names import MailToolName
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.domain.policies.security_floor import MailSecurityFloor
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentSettings
from ai_agent_lab.mail.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.infrastructure.mcp.dialects import create_dialect_registry
from ai_agent_lab.mail.infrastructure.mcp.errors import McpBindingError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def routed_backend():
    loader = SkillManifestLoader(PermissionRegistry(MailPermission.declared()), MailSecurityFloor().build())
    manifest = AgentManifestLoader(ConfigurationDirectory(ROOT / "config"), loader).load("mail")
    overrides = {"get_thread", "archive_mail", "remove_label", "delete_label", "summarise_mail"}
    skills = tuple(
        skill.model_copy(update={"mcp_server": "local" if skill.tool_name in overrides else None})
        for skill in manifest.skills
    )
    manifest = manifest.model_copy(update={"mcp_server": "gmail-api", "skills": skills})
    delegates = {}
    connections = {}

    def dialect(binding, connection, owner):
        delegates[binding.server] = AsyncMock(spec=MailTools)
        connections[binding.server] = connection
        return delegates[binding.server]

    provider = MailToolsProvider(
        MailAgentSettings(mode="mcp"),
        MailDatasetLoader(),
        manifest=manifest,
        dialects=create_dialect_registry({"native": dialect}),
    )
    yield provider, manifest, delegates, connections
    await provider.aclose()


@pytest.mark.parametrize(
    ("method", "alias", "arguments"),
    [
        ("search", "search_mail", (Mock(), Mock())),
        ("get_message", "get_mail", ("message", Mock())),
        ("get_thread", "get_thread", ("thread", Mock())),
        ("list_labels", "list_labels", (Mock(),)),
        ("create_draft", "create_draft", (Mock(), Mock())),
        ("send", "send_mail", (Mock(), Mock())),
        ("set_read_state", "mark_read", ("message", True, Mock())),
        ("archive", "archive_mail", ("message", Mock())),
        ("apply_label", "apply_label", ("message", "label", Mock())),
        ("remove_label", "remove_label", ("message", "label", Mock())),
        ("create_label", "create_label", ("label", Mock())),
        ("delete_label", "delete_label", ("label", Mock())),
    ],
)
async def test_each_operation_uses_its_own_skill_server(routed_backend, method, alias, arguments):
    provider, manifest, delegates, connections = routed_backend
    tools = provider.build(base_path=ROOT)

    await getattr(tools, method)(*arguments)

    skill = manifest.skill(alias)
    server = skill.mcp_server or manifest.mcp_server
    getattr(delegates[server], method).assert_awaited_once_with(*arguments)
    assert provider._registry.for_skill(alias).connection is connections[server]
    assert provider._registry.server_names == ("gmail-api", "local")


async def test_factory_separates_grouped_reads_from_reasoning_skill_scope(routed_backend):
    provider, manifest, delegates, _ = routed_backend
    skills = MailSkillsFactory(
        tools_for=lambda name: provider.build_for_skill(name, base_path=ROOT),
        reasoner=Mock(),
        operations=Mock(),
        policy=Mock(),
        audit=Mock(),
        owner_directory=Mock(),
        category_catalog=Mock(),
        context_builder=Mock(),
        manifest=manifest,
    ).build()
    user = Mock()
    delegates["local"].get_thread.return_value = Mock()

    await skills.read.read_thread("thread", user)
    await skills.read.read_message("message", user)
    await skills.summary._mail_tools.get_message("summary-message", user)

    delegates["local"].get_thread.assert_awaited_once_with("thread", user)
    delegates["gmail-api"].get_message.assert_awaited_once_with("message", user)
    delegates["local"].get_message.assert_awaited_once_with("summary-message", user)


async def test_scoped_tools_cannot_reopen_a_closed_registry(routed_backend):
    provider, _, _, _ = routed_backend
    scoped = provider.build_for_skill("get_mail", base_path=ROOT)
    await provider.aclose()

    with pytest.raises(McpBindingError, match="closed"):
        await scoped.get_message("message", Mock())
    with pytest.raises(McpBindingError, match="closed"):
        provider.build_for_skill("get_mail", base_path=ROOT)


def test_capability_exposure_does_not_borrow_another_skills_server():
    loader = SkillManifestLoader(PermissionRegistry(MailPermission.declared()), MailSecurityFloor().build())
    manifest = AgentManifestLoader(ConfigurationDirectory(ROOT / "config"), loader).load("mail")
    from ai_agent_lab.mail.bootstrap.composition import MailAgentCompositionRoot

    descriptors = (Mock(tool_name="summarise_mail"), Mock(tool_name="get_mail"))
    served = {"summarise_mail": frozenset(), "get_mail": frozenset({MailToolName.GET_MAIL})}
    exposed = tuple(MailAgentCompositionRoot._servable(descriptors, served, manifest))
    assert exposed == (descriptors[1],)
