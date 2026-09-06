"""Tests of the delivered configuration.

Instructions, descriptions, prompts, approval defaults and MCP bindings are
delivered separately from the code. That makes the loader a trust boundary: what
it accepts becomes the behaviour and the security posture of the agent, so what
it refuses matters as much as what it reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_agent_lab.domain.mail.permissions import MailPermission
from ai_agent_lab.domain.security.floor import SecurityFloorViolationError
from ai_agent_lab.domain.security.operations import OperationType, RiskLevel
from ai_agent_lab.domain.security.permissions import PermissionRegistry, UnknownPermissionError
from ai_agent_lab.infrastructure.config.directory import (
    CONFIG_DIR_VARIABLE,
    ConfigurationDirectory,
    ConfigurationNotFoundError,
)
from ai_agent_lab.infrastructure.config.manifests import (
    AgentManifestLoader,
    ConfigurationError,
    SkillManifestLoader,
)
from ai_agent_lab.infrastructure.config.mcp_binding import McpBindingError, McpToolBindingLoader
from ai_agent_lab.mcp.mail.catalog import MailToolCatalog
from ai_agent_lab.mcp.mail.floor import MailSecurityFloor

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

SKILL_TEMPLATE = """\
tool_name: {tool_name}
implementation: mail.example
description: An example capability.
operation:
  type: {type}
  risk: {risk}
  permission: {permission}
  confirmation_required: {confirmation}
mcp_tools:
  - get_mail
"""


@pytest.fixture(autouse=True)
def delivered_configuration(monkeypatch):
    """Read the configuration delivered with the repository, not a stray one."""
    monkeypatch.delenv(CONFIG_DIR_VARIABLE, raising=False)


def skill_loader() -> SkillManifestLoader:
    """Build the loader with the permissions and floor of the mail domain."""
    return SkillManifestLoader(
        PermissionRegistry(MailPermission.declared()),
        MailSecurityFloor().build(),
    )


def write_package(folder: Path, **overrides: str) -> Path:
    """Write one skill package with sensible defaults."""
    fields = {
        "tool_name": "example_tool",
        "type": "READ",
        "risk": "LOW",
        "permission": "mail:read",
        "confirmation": "false",
    }
    fields.update(overrides)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "skill.yaml").write_text(SKILL_TEMPLATE.format(**fields), encoding="utf-8")
    return folder


def delivered() -> ConfigurationDirectory:
    """Return the configuration delivered with the repository."""
    return ConfigurationDirectory.resolve(base_path=REPOSITORY_ROOT)


class TestConfigurationDirectory:
    """The configuration is delivered next to the code, or wherever told."""

    def test_it_defaults_to_the_config_folder(self):
        assert delivered().path == REPOSITORY_ROOT / "config"

    def test_an_environment_variable_overrides_it(self, monkeypatch, tmp_path):
        monkeypatch.setenv(CONFIG_DIR_VARIABLE, str(tmp_path))

        assert ConfigurationDirectory.resolve(base_path=REPOSITORY_ROOT).path == tmp_path

    def test_a_missing_file_names_the_variable_to_set(self, tmp_path):
        with pytest.raises(ConfigurationNotFoundError, match=CONFIG_DIR_VARIABLE):
            ConfigurationDirectory(tmp_path).require("agents", "mail")


class TestDeliveredMailConfiguration:
    """What ships with the repository must load and stay coherent."""

    def test_the_mail_agent_loads(self):
        manifest = AgentManifestLoader(delivered(), skill_loader()).load("mail")

        assert manifest.name == "mail-agent"
        assert len(manifest.skills) == 13

    def test_the_instructions_come_from_the_delivered_file(self):
        manifest = AgentManifestLoader(delivered(), skill_loader()).load("mail")

        assert "You assist the owner of a mailbox." in manifest.instructions

    def test_only_the_reasoning_capabilities_carry_a_prompt(self):
        manifest = AgentManifestLoader(delivered(), skill_loader()).load("mail")

        assert {skill.tool_name for skill in manifest.skills if skill.is_reasoning} == {
            "summarise_mail",
            "classify_mail",
            "extract_mail_actions",
            "draft_mail_reply",
        }

    def test_a_deterministic_capability_carries_no_prompt(self):
        manifest = AgentManifestLoader(delivered(), skill_loader()).load("mail")

        assert manifest.skill("search_mail").prompt == ""

    @pytest.mark.security
    def test_sending_is_delivered_as_a_confirmed_high_risk_operation(self):
        send = AgentManifestLoader(delivered(), skill_loader()).load("mail").skill("send_mail")

        assert send.operation.operation_type is OperationType.WRITE
        assert send.operation.risk_level is RiskLevel.HIGH
        assert send.operation.confirmation_required_by_default

    def test_every_capability_declares_the_mcp_tools_it_may_use(self):
        manifest = AgentManifestLoader(delivered(), skill_loader()).load("mail")

        assert all(skill.mcp_tools for skill in manifest.skills)


class TestRefusedConfiguration:
    """A configuration that cannot be trusted is refused, not repaired."""

    @pytest.mark.security
    def test_a_configuration_cannot_disarm_a_mandatory_confirmation(self, tmp_path):
        package = write_package(tmp_path / "send_mail", tool_name="send_mail", type="WRITE", risk="HIGH",
                                permission="mail:send", confirmation="false")

        with pytest.raises(SecurityFloorViolationError, match="always requires a confirmation"):
            skill_loader().load(package)

    @pytest.mark.security
    def test_a_configuration_cannot_lower_the_risk_of_sending(self, tmp_path):
        package = write_package(tmp_path / "send_mail", tool_name="send_mail", type="WRITE", risk="LOW",
                                permission="mail:send", confirmation="true")

        with pytest.raises(SecurityFloorViolationError, match="below the required HIGH"):
            skill_loader().load(package)

    @pytest.mark.security
    def test_a_permission_no_domain_declares_is_refused(self, tmp_path):
        package = write_package(tmp_path / "example_tool", permission="mail:delete")

        with pytest.raises(UnknownPermissionError, match="mail:delete"):
            skill_loader().load(package)

    def test_an_unknown_operation_type_is_refused(self, tmp_path):
        package = write_package(tmp_path / "example_tool", type="EXECUTE")

        with pytest.raises(ConfigurationError, match=r"operation\.type"):
            skill_loader().load(package)

    def test_a_package_without_a_manifest_is_refused(self, tmp_path):
        (tmp_path / "example_tool").mkdir()

        with pytest.raises(ConfigurationError, match=r"skill\.yaml"):
            skill_loader().load(tmp_path / "example_tool")

    def test_an_agent_declaring_an_undelivered_skill_is_refused(self, tmp_path):
        (tmp_path / "agents" / "mail").mkdir(parents=True)
        (tmp_path / "agents" / "mail" / "agent.yaml").write_text(
            "name: mail-agent\ndescription: Example.\nskills:\n  - missing_tool\n", encoding="utf-8"
        )
        (tmp_path / "agents" / "mail" / "AGENT.md").write_text("You assist somebody.\n", encoding="utf-8")
        write_package(tmp_path / "skills" / "mail" / "example_tool")

        loader = AgentManifestLoader(ConfigurationDirectory(tmp_path), skill_loader())

        with pytest.raises(ConfigurationError, match="missing_tool"):
            loader.load("mail")

    def test_an_agent_without_instructions_is_refused(self, tmp_path):
        (tmp_path / "agents" / "mail").mkdir(parents=True)
        (tmp_path / "agents" / "mail" / "agent.yaml").write_text(
            "name: mail-agent\ndescription: Example.\nskills:\n  - example_tool\n", encoding="utf-8"
        )
        write_package(tmp_path / "skills" / "mail" / "example_tool")

        loader = AgentManifestLoader(ConfigurationDirectory(tmp_path), skill_loader())

        with pytest.raises(ConfigurationError, match=r"AGENT\.md"):
            loader.load("mail")


class TestMcpBinding:
    """A skill names a logical tool; the binding names the deployed one."""

    def test_the_delivered_binding_covers_every_catalogued_tool(self):
        binding = McpToolBindingLoader(delivered(), MailToolCatalog()).load("mail")

        assert set(binding.as_mapping()) == {name.value for name in MailToolCatalog().names()}

    def test_it_resolves_the_remote_name_of_a_tool(self):
        binding = McpToolBindingLoader(delivered(), MailToolCatalog()).load("mail")

        assert binding.remote_name(MailToolCatalog().names()[0])

    def test_a_partial_binding_is_refused(self, tmp_path):
        (tmp_path / "mcp").mkdir()
        (tmp_path / "mcp" / "mail.yaml").write_text(
            "server: partial\ntools:\n  search_mail: remote_search\n", encoding="utf-8"
        )

        loader = McpToolBindingLoader(ConfigurationDirectory(tmp_path), MailToolCatalog())

        with pytest.raises(McpBindingError, match="no binding for"):
            loader.load("mail")

    def test_a_binding_naming_an_unknown_tool_is_refused(self, tmp_path):
        (tmp_path / "mcp").mkdir()
        catalogued = "\n".join(f"  {name.value}: {name.value}" for name in MailToolCatalog().names())
        (tmp_path / "mcp" / "mail.yaml").write_text(
            f"server: extra\ntools:\n{catalogued}\n  delete_everything: rm\n", encoding="utf-8"
        )

        loader = McpToolBindingLoader(ConfigurationDirectory(tmp_path), MailToolCatalog())

        with pytest.raises(McpBindingError, match="unknown tools"):
            loader.load("mail")
