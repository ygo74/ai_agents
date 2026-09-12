"""Tests of what an operator can see, and of what a turn can survive.

Two properties, both learned from a real session that went wrong.

A refused operation returns text to the model, which is a normal return as far
as the framework is concerned: its own log then reads "Function apply_label
succeeded". Somebody watching the console saw fifty successes and an unchanged
mailbox. A refusal has to be visible as a refusal.

And a turn can fail for reasons that have nothing to do with the mailbox - the
model provider refusing a request, most often. That ends a turn. It must not end
the conversation, along with every draft prepared in it.
"""

from __future__ import annotations

import logging

import pytest
from ygo74.agent_runtime.domains.contracts.capability_registry import SkillDescriptor
from ygo74.agent_runtime.domains.security.operations import OperationType, RiskLevel, ToolOperationDescriptor
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.core.security.errors import ConfirmationRequiredError
from ai_agent_lab.maf.tool_adapter import SkillToolAdapter
from ai_agent_lab.mail.application.cli_entrypoint import MailAgentCli
from ai_agent_lab.mail.application.console import Console
from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer
from ai_agent_lab.mail.capabilities.tool_inputs import MessageInput
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.security_floor import MailSecurityFloor

OWNER = UserContext(user_id="owner", session_id="s", permissions=MailPermission.declared())

APPLY_LABEL = ToolOperationDescriptor(
    tool_name="apply_label",
    operation_type=OperationType.WRITE,
    risk_level=RiskLevel.MEDIUM,
    required_permission=MailPermission.MANAGE,
    confirmation_required_by_default=True,
)


class TestARefusalIsVisibleAsARefusal:
    """The framework logs a refusal as a success. We do not."""

    async def test_a_refused_capability_is_logged(self, caplog):
        tool = _tool_that_refuses()

        with caplog.at_level(logging.WARNING, logger="ai_agent_lab.maf.tool_adapter"):
            await tool.func(message_id="m-1")

        assert any("apply_label" in record.message for record in caplog.records)
        assert any("did not run" in record.getMessage() for record in caplog.records)

    async def test_the_model_is_told_the_operation_did_not_happen(self):
        """A model that read "succeeded" would report success to the user."""
        tool = _tool_that_refuses()

        answer = await tool.func(message_id="m-1")

        assert "did not run" in answer
        assert "ConfirmationRequiredError" in answer

    async def test_a_capability_that_works_is_not_logged_as_a_refusal(self, caplog):
        tool = _tool_that_succeeds()

        with caplog.at_level(logging.WARNING, logger="ai_agent_lab.maf.tool_adapter"):
            await tool.func(message_id="m-1")

        assert not caplog.records


class TestOneFailedTurnDoesNotEndTheConversation:
    """A provider failure is a turn, not a session."""

    async def test_a_chat_client_failure_is_reported_and_survived(self):
        written: list[str] = []
        console = Console(reader=_typed(["do something", "exit"]), writer=written.append)
        cli = MailAgentCli(_SessionThatFails(RuntimeError("provider said no")), console, _NothingToClose())

        await cli.run()

        assert any("that turn failed" in line for line in written)
        assert any("RuntimeError" in line for line in written)

    async def test_the_conversation_continues_after_a_failed_turn(self):
        written: list[str] = []
        console = Console(reader=_typed(["first", "second", "exit"]), writer=written.append)
        session = _SessionThatFailsOnce(RuntimeError("transient"))
        cli = MailAgentCli(session, console, _NothingToClose())

        await cli.run()

        assert session.turns == 2
        assert any("second turn answered" in line for line in written)

    async def test_a_domain_failure_is_still_named(self):
        from ai_agent_lab.core.errors import DomainError

        written: list[str] = []
        console = Console(reader=_typed(["do something", "exit"]), writer=written.append)
        cli = MailAgentCli(_SessionThatFails(DomainError("mailbox unreachable")), console, _NothingToClose())

        await cli.run()

        assert any("mailbox unreachable" in line for line in written)


def _typed(answers: list[str]):
    """A reader returning scripted user input."""
    remaining = list(answers)

    def read(_label: str) -> str:
        return remaining.pop(0) if remaining else "exit"

    return read


class _SessionThatFails:
    """A session whose every turn raises."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def ask(self, message: str) -> str:
        raise self._error


class _SessionThatFailsOnce:
    """A session whose first turn raises and whose second answers."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.turns = 0

    async def ask(self, message: str) -> str:
        self.turns += 1
        if self.turns == 1:
            raise self._error
        return "second turn answered"


class _NothingToClose:
    """A runtime holding no backend."""

    async def aclose(self) -> None:
        """Nothing to release."""


def _adapter() -> SkillToolAdapter:
    """An adapter whose policy gates every mailbox change."""
    policy = ConfiguredConfirmationPolicy(InMemoryConfirmationPreferenceStore(), MailSecurityFloor().build())
    return SkillToolAdapter(MailToolResultRenderer(), policy)


def _tool_that_refuses():
    """A tool whose capability refuses for want of a confirmation."""

    async def invoke(payload, user):
        raise ConfirmationRequiredError("apply_label")

    return _adapter().to_tool(_descriptor(invoke), OWNER)


def _tool_that_succeeds():
    """A tool whose capability runs."""

    async def invoke(payload, user):
        from ai_agent_lab.mail.capabilities.results import OperationAcknowledged

        return OperationAcknowledged(tool_name="apply_label", message_id="m-1", detail="done")

    return _adapter().to_tool(_descriptor(invoke), OWNER)


def _descriptor(invoke) -> SkillDescriptor:
    """A capability descriptor around one coroutine."""
    return SkillDescriptor(
        tool_name="apply_label",
        description="Attach a label to a message.",
        input_model=MessageInput,
        operation=APPLY_LABEL,
        invoke=invoke,
    )


@pytest.fixture(autouse=True)
def _quiet_logging(caplog):
    """Keep the adapter logger reachable by the tests."""
    caplog.set_level(logging.WARNING)
