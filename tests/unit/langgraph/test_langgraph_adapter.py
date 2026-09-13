"""Tests of the LangGraph adapter.

They check the two things the adapter must never get wrong: that a capability is
gated because the deterministic confirmation policy says so, and that the only
answers a gated capability accepts are approval and refusal.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from ygo74.agent_runtime.domains.contracts.capability_registry import SkillDescriptor, SkillRegistry
from ygo74.agent_runtime.domains.humanapproval.confirmation import (
    ConfiguredConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ygo74.agent_runtime.domains.security.floor import OperationFloor, SecurityFloor
from ygo74.agent_runtime.domains.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ygo74.agent_runtime.domains.security.permissions import Permission
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.langgraph.approval import (
    ALLOWED_DECISIONS,
    LangGraphApprovalTranslator,
    PendingToolApproval,
)
from ai_agent_lab.langgraph.tool_adapter import SkillToolAdapter

READ_TOOL = "read_something"
WRITE_TOOL = "change_something"

PERMISSION = Permission("test", "act")


class Payload(BaseModel):
    """Arguments of the fake capability."""

    value: str


class Result(BaseModel):
    """Result of the fake capability."""

    text: str


class CapabilityRefusedError(DomainError):
    """A domain failure raised by the fake capability."""


class TextRenderer:
    """Renders a result as the text a model reads."""

    def render(self, result: Any) -> str:
        """Return the rendered result."""
        return getattr(result, "text", str(result))


def descriptor(name: str, *, write: bool, confirm: bool) -> ToolOperationDescriptor:
    """Build the security metadata of a fake capability."""
    return ToolOperationDescriptor(
        tool_name=name,
        operation_type=OperationType.WRITE if write else OperationType.READ,
        risk_level=RiskLevel.HIGH if write else RiskLevel.LOW,
        required_permission=PERMISSION,
        confirmation_required_by_default=confirm,
    )


def skill(name: str, *, write: bool, confirm: bool, fails: bool = False) -> SkillDescriptor:
    """Build a fake capability."""

    async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
        del user
        if fails:
            raise CapabilityRefusedError("the wiki refused")
        return Result(text=f"ran with {getattr(payload, 'value', '')}")

    return SkillDescriptor(
        tool_name=name,
        description=f"The {name} capability.",
        input_model=Payload,
        operation=descriptor(name, write=write, confirm=confirm),
        invoke=invoke,
    )


@pytest.fixture
def user() -> UserContext:
    """A user holding the permission the fake capabilities require."""
    return UserContext(user_id="someone", session_id="s1", permissions=frozenset({PERMISSION}))


@pytest.fixture
def policy() -> ConfiguredConfirmationPolicy:
    """A policy over a floor that pins the write capability."""
    return ConfiguredConfirmationPolicy(
        InMemoryConfirmationPreferenceStore({}),
        SecurityFloor(
            (
                OperationFloor(
                    tool_name=WRITE_TOOL,
                    minimum_risk=RiskLevel.HIGH,
                    confirmation_always_required=True,
                ),
            )
        ),
    )


class TestSkillToolAdapter:
    """Skills become LangChain tools without being rewritten."""

    async def test_a_capability_becomes_a_tool_carrying_its_contract(self, user: UserContext):
        tool = SkillToolAdapter(TextRenderer()).to_tool(skill(READ_TOOL, write=False, confirm=False), user)

        assert tool.name == READ_TOOL
        assert tool.description == f"The {READ_TOOL} capability."
        assert tool.args_schema is Payload

    async def test_running_a_tool_renders_the_skill_result(self, user: UserContext):
        tool = SkillToolAdapter(TextRenderer()).to_tool(skill(READ_TOOL, write=False, confirm=False), user)

        assert await tool.ainvoke({"value": "x"}) == "ran with x"

    async def test_a_domain_failure_is_reported_not_raised(self, user: UserContext):
        """The model must learn the operation did not happen, and say so."""
        tool = SkillToolAdapter(TextRenderer()).to_tool(skill(WRITE_TOOL, write=True, confirm=True, fails=True), user)

        answer = await tool.ainvoke({"value": "x"})

        assert "did not run" in answer
        assert "CapabilityRefusedError" in answer

    async def test_a_domain_failure_is_logged_as_a_warning(self, user: UserContext, caplog):
        """The framework records a successful call, so the log must not."""
        tool = SkillToolAdapter(TextRenderer()).to_tool(skill(WRITE_TOOL, write=True, confirm=True, fails=True), user)

        with caplog.at_level("WARNING"):
            await tool.ainvoke({"value": "x"})

        assert any(WRITE_TOOL in record.getMessage() for record in caplog.records)

    async def test_every_capability_of_a_registry_is_exposed(self, user: UserContext):
        registry = SkillRegistry(
            skills=[skill(READ_TOOL, write=False, confirm=False), skill(WRITE_TOOL, write=True, confirm=True)]
        )

        tools = SkillToolAdapter(TextRenderer()).to_tools(registry, user)

        assert [tool.name for tool in tools] == [READ_TOOL, WRITE_TOOL]


class TestInterruptPolicy:
    """Which capabilities the framework suspends, and on whose authority."""

    def test_the_policy_decides_what_is_gated(self, policy: ConfiguredConfirmationPolicy, user: UserContext):
        registry = SkillRegistry(
            skills=[skill(READ_TOOL, write=False, confirm=False), skill(WRITE_TOOL, write=True, confirm=True)]
        )

        mapping = LangGraphApprovalTranslator().interrupt_on(registry, policy, user)

        assert mapping[READ_TOOL] is False
        assert mapping[WRITE_TOOL] is not False

    def test_ungated_capabilities_are_listed_explicitly(self, policy: ConfiguredConfirmationPolicy, user: UserContext):
        """A missing entry means "never interrupt", so a typo must not ungate."""
        registry = SkillRegistry(skills=[skill(READ_TOOL, write=False, confirm=False)])

        mapping = LangGraphApprovalTranslator().interrupt_on(registry, policy, user)

        assert READ_TOOL in mapping

    @pytest.mark.security
    def test_a_gated_capability_accepts_only_approval_and_refusal(
        self, policy: ConfiguredConfirmationPolicy, user: UserContext
    ):
        """`edit` would run arguments nobody confirmed; `respond` would fake success."""
        registry = SkillRegistry(skills=[skill(WRITE_TOOL, write=True, confirm=True)])

        mapping = LangGraphApprovalTranslator().interrupt_on(registry, policy, user)

        allowed = mapping[WRITE_TOOL]["allowed_decisions"]  # type: ignore[index]
        assert sorted(allowed) == ["approve", "reject"]
        assert "edit" not in allowed
        assert "respond" not in allowed

    @pytest.mark.security
    def test_the_allowed_decisions_are_fixed_in_code(self):
        assert ALLOWED_DECISIONS == ("approve", "reject")


class FakeInterrupt:
    """Stands in for a framework interrupt."""

    def __init__(self, value: Any) -> None:
        self.value = value


def interrupt_over(*names: str) -> FakeInterrupt:
    """Build an interrupt suspending the given capabilities."""
    return FakeInterrupt(
        {
            "action_requests": [{"name": name, "args": {"value": name}} for name in names],
            "review_configs": [{"action_name": name, "allowed_decisions": list(ALLOWED_DECISIONS)} for name in names],
        }
    )


class TestReadingInterrupts:
    """Turning framework interrupts into the application's vocabulary."""

    def test_every_suspended_call_is_reported(self):
        pending = LangGraphApprovalTranslator().pending_approvals([interrupt_over("a", "b")])

        assert [approval.tool_name for approval in pending] == ["a", "b"]

    def test_a_suspended_call_carries_the_proposed_arguments(self):
        pending = LangGraphApprovalTranslator().pending_approvals([interrupt_over(WRITE_TOOL)])

        assert pending[0].arguments == {"value": WRITE_TOOL}

    def test_no_interrupt_means_nothing_pending(self):
        assert LangGraphApprovalTranslator().pending_approvals([]) == ()

    def test_an_interrupt_from_elsewhere_is_ignored(self):
        """Another middleware's interrupt is not an approval request."""
        pending = LangGraphApprovalTranslator().pending_approvals([FakeInterrupt("some other pause")])

        assert pending == ()

    def test_a_malformed_payload_is_ignored_rather_than_guessed_at(self):
        pending = LangGraphApprovalTranslator().pending_approvals([FakeInterrupt({"action_requests": "not a list"})])

        assert pending == ()


class TestAnsweringInterrupts:
    """Building the answer that resumes a suspended call."""

    def test_approving_produces_an_approve_decision(self):
        approval = PendingToolApproval({"name": WRITE_TOOL, "args": {}})

        assert approval.answer(approved=True) == {"type": "approve"}

    def test_declining_produces_a_reject_decision_with_a_reason(self):
        approval = PendingToolApproval({"name": WRITE_TOOL, "args": {}})

        answer = approval.answer(approved=False)

        assert answer["type"] == "reject"
        assert answer["message"]

    def test_the_resume_command_carries_the_decisions_in_order(self):
        translator = LangGraphApprovalTranslator()
        pending = translator.pending_approvals([interrupt_over("a", "b")])

        command = translator.resume_command([pending[0].answer(approved=True), pending[1].answer(approved=False)])

        decisions = command.resume["decisions"]
        assert [decision["type"] for decision in decisions] == ["approve", "reject"]
