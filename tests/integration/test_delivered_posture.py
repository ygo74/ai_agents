"""Tests that the delivered configuration is the one that runs.

Two guards decide whether a mailbox change happens. The framework adapter
decides whether to suspend the call and ask; the skill decides whether to run
it. They are deliberately independent, so that neither a change of orchestration
nor a change of framework can weaken the rule.

Independent must not mean differently informed. A capability the framework never
asks about and the skill always refuses cannot be performed at all, and the
model - told only that the operation was refused - reports that the mailbox
turned it down. That is what happens the moment the two read different sources,
and it happened: the adapter read the delivered skill package while the skill
read a hard-coded catalogue.

These tests deliver a configuration and check that both guards obey it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.support.maf_fakes import ScriptedChatClient, says

from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

GATED = """\
tool_name: apply_label
implementation: mail.apply_label
description: >-
  Attach a label or category to a message. Modifies the mailbox.
operation:
  type: WRITE
  risk: MEDIUM
  permission: mail:manage
  confirmation_required: true
mcp_tools:
  - apply_label
  - list_labels
"""

UNGATED = GATED.replace("confirmation_required: true", "confirmation_required: false")


@pytest.fixture
def delivered(tmp_path, monkeypatch):
    """A copy of the delivered configuration this test may rewrite."""
    root = tmp_path / "config"
    shutil.copytree(REPOSITORY_ROOT / "config", root)
    monkeypatch.setenv("AI_AGENT_LAB_CONFIG_DIR", str(root))
    return root


def runtime_for(delivered: Path, posture: str):
    """Build a runtime under a given posture for ``apply_label``."""
    (delivered / "skills" / "mail" / "apply_label" / "skill.yaml").write_text(posture, encoding="utf-8")
    return MailAgentCompositionRoot(
        MailAgentSettings(),
        ScriptedChatClient([says("nothing to do")]),
        reasoner=ScriptedTextReasoner({}),
        base_path=REPOSITORY_ROOT,
    ).build(session_id="delivered")


class TestBothGuardsReadTheSameConfiguration:
    """What the skill package says is what both guards do."""

    @pytest.mark.parametrize("posture", [GATED, UNGATED], ids=["gated", "ungated"])
    def test_the_two_guards_agree(self, delivered, posture):
        runtime = runtime_for(delivered, posture)
        descriptor = _descriptor_of(runtime, MailToolName.APPLY_LABEL)

        framework_asks = runtime.policy.requires_confirmation(descriptor.operation, runtime.user)
        domain_asks = runtime.skills.management.requires_confirmation(MailToolName.APPLY_LABEL, runtime.user)

        assert framework_asks == domain_asks

    def test_a_gated_package_makes_both_guards_ask(self, delivered):
        runtime = runtime_for(delivered, GATED)
        descriptor = _descriptor_of(runtime, MailToolName.APPLY_LABEL)

        assert runtime.policy.requires_confirmation(descriptor.operation, runtime.user)
        assert runtime.skills.management.requires_confirmation(MailToolName.APPLY_LABEL, runtime.user)

    async def test_an_ungated_package_lets_the_operation_run(self, delivered):
        """The defect this pins: ungating made the capability impossible."""
        runtime = runtime_for(delivered, UNGATED)

        await runtime.skills.management.apply_label("m-alpha-1", "PROJECT_ALPHA", runtime.user)

        message = await runtime.mail_tools.get_message("m-alpha-1", runtime.user)
        assert "PROJECT_ALPHA" in message.label_ids

    @pytest.mark.security
    async def test_ungating_never_reaches_an_operation_on_the_floor(self, delivered):
        """A package cannot ungate sending, whatever it declares."""
        package = delivered / "skills" / "mail" / "send_mail" / "skill.yaml"
        package.write_text(
            package.read_text(encoding="utf-8").replace("confirmation_required: true", "confirmation_required: false"),
            encoding="utf-8",
        )

        with pytest.raises(Exception, match="send_mail"):
            runtime_for(delivered, GATED)


def _descriptor_of(runtime, tool: MailToolName):
    """The registered capability for a tool."""
    return next(item for item in runtime.registry.skills if item.tool_name == tool.value)
