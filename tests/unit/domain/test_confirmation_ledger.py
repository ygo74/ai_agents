"""Tests of the confirmation ledger.

The ledger carries a user's answer, and the exact request they were shown, from
the moment the agent framework collected it to the moment the operation runs.
Getting this wrong would let an approval authorise the wrong thing, so its rules
are pinned here.
"""

from __future__ import annotations

import pytest

from ai_agent_lab.domain.security.confirmation import (
    ConfirmationDecision,
    ConfirmationKey,
    ConfirmationOutcome,
    ConfirmationRequest,
)
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.domain.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.infrastructure.inmemory.confirmation_ledger import InMemoryConfirmationLedger

OWNER = UserContext(user_id="owner", session_id="s1", permissions=frozenset(Permission))
INTRUDER = UserContext(user_id="intruder", session_id="s2", permissions=frozenset(Permission))

SEND = ToolOperationDescriptor(
    tool_name="send_mail",
    operation_type=OperationType.WRITE,
    risk_level=RiskLevel.HIGH,
    required_permission=Permission.MAIL_SEND,
    confirmation_required_by_default=True,
)


def outcome(target: str, *, approved: bool = True, request_id: str = "req-1", user: str = "owner"):
    """Build an answered confirmation for a target."""
    request = ConfirmationRequest(
        request_id=request_id,
        operation=SEND,
        requested_for=user,
        title="Send this email?",
        target=target,
    )
    decision = ConfirmationDecision(request_id=request_id, approved=approved, decided_by=user)
    return ConfirmationOutcome(request=request, decision=decision)


def key(target: str) -> ConfirmationKey:
    """Build the key naming a send operation on a target."""
    return ConfirmationKey(tool_name="send_mail", target=target)


class TestInMemoryConfirmationLedger:
    """Rules the ledger must never break."""

    def test_returns_the_recorded_answer(self):
        ledger = InMemoryConfirmationLedger()
        ledger.record(outcome("draft-1"), OWNER)

        taken = ledger.take(key("draft-1"), OWNER)

        assert taken is not None
        assert taken.decision.approved
        assert taken.request.request_id == "req-1"

    @pytest.mark.security
    def test_an_answer_is_consumed_once(self):
        ledger = InMemoryConfirmationLedger()
        ledger.record(outcome("draft-1"), OWNER)

        assert ledger.take(key("draft-1"), OWNER) is not None
        assert ledger.take(key("draft-1"), OWNER) is None

    @pytest.mark.security
    def test_an_answer_never_applies_to_another_target(self):
        ledger = InMemoryConfirmationLedger()
        ledger.record(outcome("draft-1"), OWNER)

        assert ledger.take(key("draft-2"), OWNER) is None

    @pytest.mark.security
    def test_an_answer_never_applies_to_another_user(self):
        ledger = InMemoryConfirmationLedger()
        ledger.record(outcome("draft-1"), OWNER)

        assert ledger.take(key("draft-1"), INTRUDER) is None
        assert ledger.take(key("draft-1"), OWNER) is not None

    def test_a_refusal_is_carried_as_faithfully_as_an_approval(self):
        ledger = InMemoryConfirmationLedger()
        ledger.record(outcome("draft-1", approved=False), OWNER)

        taken = ledger.take(key("draft-1"), OWNER)

        assert taken is not None
        assert not taken.decision.approved

    def test_repeated_answers_are_consumed_in_order(self):
        ledger = InMemoryConfirmationLedger()
        ledger.record(outcome("draft-1", request_id="first"), OWNER)
        ledger.record(outcome("draft-1", request_id="second"), OWNER)

        assert ledger.take(key("draft-1"), OWNER).request.request_id == "first"
        assert ledger.take(key("draft-1"), OWNER).request.request_id == "second"

    @pytest.mark.security
    def test_discard_drops_only_the_answers_of_one_user(self):
        ledger = InMemoryConfirmationLedger()
        ledger.record(outcome("draft-1"), OWNER)
        ledger.record(outcome("draft-2", user="intruder"), INTRUDER)

        ledger.discard(OWNER)

        assert ledger.pending_count(OWNER) == 0
        assert ledger.pending_count(INTRUDER) == 1
