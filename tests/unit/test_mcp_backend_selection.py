"""Mail and Wiki honor skill overrides before the agent's default MCP backend."""

from pathlib import Path

import pytest
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.configuration.manifests import AgentManifestLoader, SkillManifestLoader
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry

from ai_agent_lab.mail.bootstrap.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.domain.policies.security_floor import MailSecurityFloor
from ai_agent_lab.mail.infrastructure.mcp.errors import McpBindingError as MailMcpBindingError
from ai_agent_lab.wiki.bootstrap.wiki_tools_provider import WikiToolsProvider
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.domain.policies.security_floor import WikiSecurityFloor
from ai_agent_lab.wiki.infrastructure.mcp.errors import McpBindingError as WikiMcpBindingError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["mail", "wiki"])
def backend(request):
    """Use real manifests, then isolate the effective server declarations under test."""
    if request.param == "mail":
        permissions, floor = MailPermission.declared(), MailSecurityFloor().build()
        provider, error = MailToolsProvider, MailMcpBindingError
    else:
        permissions, floor = WikiPermission.declared(), WikiSecurityFloor().build()
        provider, error = WikiToolsProvider, WikiMcpBindingError
    loader = SkillManifestLoader(PermissionRegistry(permissions), floor)
    manifest = AgentManifestLoader(ConfigurationDirectory(ROOT / "config"), loader).load(request.param)
    skills = tuple(skill.model_copy(update={"mcp_server": None}) for skill in manifest.skills)
    return provider, error, manifest.model_copy(update={"skills": skills, "mcp_server": "default-backend"})


def test_skills_inherit_agent_default(backend):
    provider, _, manifest = backend
    assert provider.server_for(manifest) == "default-backend"


@pytest.mark.parametrize("default", [None, "default-backend"])
def test_explicit_skill_servers_override_agent_default(backend, default):
    provider, _, manifest = backend
    skills = tuple(
        skill.model_copy(update={"mcp_server": "override-backend"}) if skill.mcp_tools else skill
        for skill in manifest.skills
    )
    selected = manifest.model_copy(update={"skills": skills, "mcp_server": default})
    assert provider.server_for(selected) == "override-backend"


def test_explicit_same_server_and_inherited_default_can_mix(backend):
    provider, _, manifest = backend
    changed = manifest.skills[0].model_copy(update={"mcp_server": "default-backend"})
    selected = manifest.model_copy(update={"skills": (changed, *manifest.skills[1:])})
    assert provider.server_for(selected) == "default-backend"


def test_conflicting_effective_servers_are_refused(backend):
    provider, error, manifest = backend
    changed = manifest.skills[0].model_copy(update={"mcp_server": "other-backend"})
    selected = manifest.model_copy(update={"skills": (changed, *manifest.skills[1:])})
    with pytest.raises(error, match="one MCP server"):
        provider.server_for(selected)


def test_missing_effective_server_is_refused(backend):
    provider, error, manifest = backend
    with pytest.raises(error, match="mcp_server"):
        provider.server_for(manifest.model_copy(update={"mcp_server": None}))


def test_non_mcp_skills_do_not_select_a_backend(backend):
    provider, _, manifest = backend
    changed = manifest.skills[0].model_copy(update={"mcp_tools": (), "mcp_server": "unused-backend"})
    selected = manifest.model_copy(update={"skills": (changed, *manifest.skills[1:])})
    assert provider.server_for(selected) == "default-backend"
