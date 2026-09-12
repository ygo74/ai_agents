"""Integration tests of the Microsoft Agent Framework adapter.

They check the one thing the adapter must never get wrong: that the approval
mode of a framework tool comes from the deterministic confirmation policy, for
the user the agent acts for.
"""

from __future__ import annotations

import pytest
from tests.support.maf_fakes import ScriptedChatClient, says
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.maf.tool_adapter import SkillToolAdapter
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.capabilities.read_capabilities import CLASSIFY_MAIL, SUMMARISE_MAIL
from ai_agent_lab.mail.capabilities.write_capabilities import DRAFT_MAIL_REPLY
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner
from ai_agent_lab.mail.security_floor import MailSecurityFloor

REPOSITORY_ROOT_MARKER = "data"

READ_ONLY_TOOLS = frozenset(
    {
        MailToolName.SEARCH_MAIL.value,
        MailToolName.GET_MAIL.value,
        MailToolName.GET_THREAD.value,
        MailToolName.LIST_LABELS.value,
        SUMMARISE_MAIL,
        CLASSIFY_MAIL,
        DRAFT_MAIL_REPLY,
    }
)


def build_runtime(settings: MailAgentSettings | None = None):
    """Assemble the Mail Agent with a scripted model and the sample dataset."""
    from pathlib import Path

    return MailAgentCompositionRoot(
        settings or MailAgentSettings(),
        ScriptedChatClient([says("nothing to do")]),
        reasoner=ScriptedTextReasoner({}),
        base_path=Path(__file__).resolve().parents[2],
    ).build(session_id="integration")


def tools_of(runtime, settings: MailAgentSettings | None = None):
    """Expose the agent capabilities as framework tools."""
    resolved = settings or MailAgentSettings()
    policy = ConfiguredConfirmationPolicy(
        InMemoryConfirmationPreferenceStore({resolved.user_id: resolved.confirmation_preferences()}),
        MailSecurityFloor().build(),
    )
    from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer

    adapter = SkillToolAdapter(MailToolResultRenderer(), policy)
    return {tool.name: tool for tool in adapter.to_tools(runtime.registry, runtime.user)}


class TestToolRegistration:
    """Every capability reaches the model with the right contract."""

    def test_every_capability_is_exposed(self):
        runtime = build_runtime()

        names = set(tools_of(runtime))

        assert MailToolName.SEND_MAIL.value in names
        assert names >= READ_ONLY_TOOLS

    def test_read_only_capabilities_are_never_gated(self):
        runtime = build_runtime()

        tools = tools_of(runtime)

        assert all(tools[name].approval_mode == "never_require" for name in READ_ONLY_TOOLS)

    def test_state_changing_capabilities_are_gated_by_default(self):
        runtime = build_runtime()

        tools = tools_of(runtime)

        gated = {MailToolName.SEND_MAIL, MailToolName.ARCHIVE_MAIL, MailToolName.MARK_READ}
        assert all(tools[tool.value].approval_mode == "always_require" for tool in gated)

    def test_each_capability_advertises_a_schema_and_a_description(self):
        runtime = build_runtime()

        for tool in tools_of(runtime).values():
            assert tool.description
            assert tool.parameters()["type"] == "object"


class TestApprovalModeFollowsConfiguration:
    """The approval mode is data driven, exactly like the policy."""

    def test_a_low_risk_write_can_be_auto_approved(self, monkeypatch):
        monkeypatch.setenv("MAIL_AGENT_AUTO_APPROVED_TOOLS", MailToolName.MARK_READ.value)
        settings = MailAgentSettings()

        tools = tools_of(build_runtime(settings), settings)

        assert tools[MailToolName.MARK_READ.value].approval_mode == "never_require"

    @pytest.mark.security
    def test_sending_stays_gated_whatever_the_configuration(self, monkeypatch):
        monkeypatch.setenv("MAIL_AGENT_AUTO_APPROVED_TOOLS", f"{MailToolName.SEND_MAIL.value},mark_read")
        settings = MailAgentSettings()

        tools = tools_of(build_runtime(settings), settings)

        assert tools[MailToolName.SEND_MAIL.value].approval_mode == "always_require"

    def test_a_capability_can_be_forced_to_require_confirmation(self, monkeypatch):
        monkeypatch.setenv("MAIL_AGENT_ALWAYS_CONFIRM_TOOLS", MailToolName.GET_MAIL.value)
        settings = MailAgentSettings()

        tools = tools_of(build_runtime(settings), settings)

        assert tools[MailToolName.GET_MAIL.value].approval_mode == "always_require"

    def test_preferences_are_scoped_to_the_configured_user(self, monkeypatch):
        monkeypatch.setenv("MAIL_AGENT_AUTO_APPROVED_TOOLS", MailToolName.ARCHIVE_MAIL.value)
        settings = MailAgentSettings()
        runtime = build_runtime(settings)
        stranger = UserContext(user_id="somebody-else", session_id="s", permissions=MailPermission.declared())

        policy = ConfiguredConfirmationPolicy(
            InMemoryConfirmationPreferenceStore({settings.user_id: settings.confirmation_preferences()}),
            MailSecurityFloor().build(),
        )
        from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer

        adapter = SkillToolAdapter(MailToolResultRenderer(), policy)
        for_owner = {tool.name: tool for tool in adapter.to_tools(runtime.registry, runtime.user)}
        for_stranger = {tool.name: tool for tool in adapter.to_tools(runtime.registry, stranger)}

        assert for_owner[MailToolName.ARCHIVE_MAIL.value].approval_mode == "never_require"
        assert for_stranger[MailToolName.ARCHIVE_MAIL.value].approval_mode == "always_require"


class TestErrorReporting:
    """A domain failure is reported to the model, never swallowed."""

    async def test_a_domain_error_becomes_a_readable_refusal(self):
        runtime = build_runtime()
        tools = tools_of(runtime)

        result = await tools[MailToolName.GET_MAIL.value].invoke(arguments={"message_id": "does-not-exist"})

        rendered = "".join(str(getattr(content, "text", "")) for content in result)
        assert "did not run" in rendered
        assert "MailNotFoundError" in rendered


class TestLabelDiscovery:
    """Applying a label needs identifiers the model must be able to discover."""

    async def test_the_agent_can_list_the_labels_of_the_mailbox(self):
        runtime = build_runtime()
        tools = tools_of(runtime)

        result = await tools[MailToolName.LIST_LABELS.value].invoke(arguments={})

        rendered = "".join(str(getattr(content, "text", "")) for content in result)
        assert "PROJECT_ALPHA" in rendered
        assert "FINANCE" in rendered

    def test_listing_labels_is_never_gated(self):
        runtime = build_runtime()

        assert tools_of(runtime)[MailToolName.LIST_LABELS.value].approval_mode == "never_require"
