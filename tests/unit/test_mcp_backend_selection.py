"""Legacy single-server helpers use the agent default before skill fallbacks.

Normal manifest-driven execution routes each skill through its own registry
binding; those paths are covered by the Mail and Wiki registry routing tests.
"""

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


def test_agent_default_is_used_by_legacy_helper_even_with_skill_overrides(backend):
    provider, _, manifest = backend
    skills = tuple(
        skill.model_copy(update={"mcp_server": "override-backend"}) if skill.mcp_tools else skill
        for skill in manifest.skills
    )
    selected = manifest.model_copy(update={"skills": skills})
    assert provider.server_for(selected) == "default-backend"


def test_legacy_helper_falls_back_to_a_skill_server_without_agent_default(backend):
    provider, _, manifest = backend
    skills = tuple(
        skill.model_copy(update={"mcp_server": "override-backend"}) if index == 0 else skill
        for index, skill in enumerate(manifest.skills)
    )
    selected = manifest.model_copy(update={"skills": skills, "mcp_server": None})
    assert provider.server_for(selected) == "override-backend"


def test_explicit_same_server_and_inherited_default_can_mix(backend):
    provider, _, manifest = backend
    changed = manifest.skills[0].model_copy(update={"mcp_server": "default-backend"})
    selected = manifest.model_copy(update={"skills": (changed, *manifest.skills[1:])})
    assert provider.server_for(selected) == "default-backend"


def test_missing_effective_server_is_refused(backend):
    provider, error, manifest = backend
    with pytest.raises(error, match="mcp_server"):
        provider.server_for(manifest.model_copy(update={"mcp_server": None}))


def test_non_mcp_skills_do_not_select_a_backend(backend):
    provider, _, manifest = backend
    changed = manifest.skills[0].model_copy(update={"mcp_tools": (), "mcp_server": "unused-backend"})
    selected = manifest.model_copy(update={"skills": (changed, *manifest.skills[1:])})
    assert provider.server_for(selected) == "default-backend"
