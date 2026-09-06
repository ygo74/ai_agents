"""Tests of the deterministic confirmation policy."""

from __future__ import annotations

import pytest

from ai_agent_lab.domain.mail.permissions import MailPermission
from ai_agent_lab.domain.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationDecision,
    ConfirmationGate,
    ConfirmationPreferences,
    ConfirmationRequest,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.domain.security.errors import (
    AuthorizationError,
    ConfirmationMismatchError,
    ConfirmationRejectedError,
    ConfirmationRequiredError,
)
from ai_agent_lab.domain.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.domain.security.permissions import Permission


def descriptor(
    tool_name: str,
    *,
    operation_type: OperationType = OperationType.WRITE,
    risk_level: RiskLevel = RiskLevel.LOW,
    permission: Permission = MailPermission.MANAGE,
    default: bool = True,
) -> ToolOperationDescriptor:
    """Build a tool operation descriptor."""
    return ToolOperationDescriptor(
        tool_name=tool_name,
        operation_type=operation_type,
        risk_level=risk_level,
        required_permission=permission,
        confirmation_required_by_default=default,
    )


READ_OP = descriptor(
    "search_mail",
    operation_type=OperationType.READ,
    risk_level=RiskLevel.LOW,
    permission=MailPermission.READ,
    default=False,
)
MARK_READ_OP = descriptor("mark_read", risk_level=RiskLevel.LOW, default=True)
ARCHIVE_OP = descriptor("archive_mail", risk_level=RiskLevel.MEDIUM, default=True)
SEND_OP = descriptor("send_mail", risk_level=RiskLevel.HIGH, permission=MailPermission.SEND, default=True)


def policy_with(preferences: ConfirmationPreferences | None = None) -> ConfiguredConfirmationPolicy:
    """Build a policy holding the given preferences for the ``owner`` user."""
    store = InMemoryConfirmationPreferenceStore(
        {"owner": preferences} if preferences is not None else None,
    )
    return ConfiguredConfirmationPolicy(store)


class TestConfiguredConfirmationPolicy:
    """Decision table of the confirmation policy."""

    def test_read_operations_are_never_gated(self, owner):
        assert not policy_with().requires_confirmation(READ_OP, owner)

    @pytest.mark.parametrize("operation", [MARK_READ_OP, ARCHIVE_OP, SEND_OP])
    def test_write_operations_are_gated_by_default(self, owner, operation):
        assert policy_with().requires_confirmation(operation, owner)

    def test_user_can_auto_approve_a_low_risk_write(self, owner):
        policy = policy_with(ConfirmationPreferences(auto_approved_tools=frozenset({"mark_read"})))

        assert not policy.requires_confirmation(MARK_READ_OP, owner)

    def test_user_can_auto_approve_a_medium_risk_write(self, owner):
        policy = policy_with(ConfirmationPreferences(auto_approved_tools=frozenset({"archive_mail"})))

        assert not policy.requires_confirmation(ARCHIVE_OP, owner)

    @pytest.mark.security
    def test_high_risk_writes_cannot_be_auto_approved(self, owner):
        policy = policy_with(ConfirmationPreferences(auto_approved_tools=frozenset({"send_mail"})))

        assert policy.requires_confirmation(SEND_OP, owner)

    def test_always_confirm_wins_over_auto_approve(self, owner):
        policy = policy_with(
            ConfirmationPreferences(
                auto_approved_tools=frozenset({"mark_read"}),
                always_confirm_tools=frozenset({"mark_read"}),
            )
        )

        assert policy.requires_confirmation(MARK_READ_OP, owner)

    def test_a_read_can_be_forced_to_require_confirmation(self, owner):
        policy = policy_with(ConfirmationPreferences(always_confirm_tools=frozenset({"search_mail"})))

        assert policy.requires_confirmation(READ_OP, owner)

    def test_preferences_are_scoped_to_a_user(self, owner, reader):
        store = InMemoryConfirmationPreferenceStore(
            {"owner": ConfirmationPreferences(auto_approved_tools=frozenset({"mark_read"}))}
        )
        policy = ConfiguredConfirmationPolicy(store)

        assert not policy.requires_confirmation(MARK_READ_OP, owner)
        assert policy.requires_confirmation(MARK_READ_OP, reader)

    def test_risk_floor_is_configurable(self, owner):
        store = InMemoryConfirmationPreferenceStore(
            {"owner": ConfirmationPreferences(auto_approved_tools=frozenset({"archive_mail"}))}
        )
        policy = ConfiguredConfirmationPolicy(store, non_overridable_risk=RiskLevel.MEDIUM)

        assert policy.requires_confirmation(ARCHIVE_OP, owner)


def request_for(
    operation: ToolOperationDescriptor,
    request_id: str = "req-1",
    requested_for: str = "owner",
) -> ConfirmationRequest:
    """Build a confirmation request for an operation."""
    return ConfirmationRequest(
        request_id=request_id,
        operation=operation,
        requested_for=requested_for,
        title="Confirm",
    )


class TestConfirmationGate:
    """Enforcement performed independently of any agent framework."""

    def test_allows_an_ungated_operation_without_a_decision(self, owner):
        ConfirmationGate(policy_with()).ensure_approved(READ_OP, owner, None, None)

    @pytest.mark.security
    def test_rejects_a_gated_operation_without_a_decision(self, owner):
        with pytest.raises(ConfirmationRequiredError):
            ConfirmationGate(policy_with()).ensure_approved(SEND_OP, owner, None, None)

    @pytest.mark.security
    def test_rejects_a_declined_operation(self, owner):
        request = request_for(SEND_OP)
        decision = ConfirmationDecision(request_id="req-1", approved=False, decided_by="owner")

        with pytest.raises(ConfirmationRejectedError):
            ConfirmationGate(policy_with()).ensure_approved(SEND_OP, owner, request, decision)

    @pytest.mark.security
    def test_rejects_a_confirmation_issued_for_another_request(self, owner):
        request = request_for(SEND_OP, "req-1")
        replayed = ConfirmationDecision(request_id="req-other", approved=True, decided_by="owner")

        with pytest.raises(ConfirmationMismatchError):
            ConfirmationGate(policy_with()).ensure_approved(SEND_OP, owner, request, replayed)

    @pytest.mark.security
    def test_rejects_an_approval_granted_by_another_user(self, owner):
        request = request_for(SEND_OP)
        borrowed = ConfirmationDecision(request_id="req-1", approved=True, decided_by="somebody-else")

        with pytest.raises(ConfirmationMismatchError):
            ConfirmationGate(policy_with()).ensure_approved(SEND_OP, owner, request, borrowed)

    @pytest.mark.security
    def test_rejects_a_request_issued_for_another_user(self, owner):
        request = request_for(SEND_OP, requested_for="somebody-else")
        decision = ConfirmationDecision(request_id="req-1", approved=True, decided_by="owner")

        with pytest.raises(ConfirmationMismatchError):
            ConfirmationGate(policy_with()).ensure_approved(SEND_OP, owner, request, decision)

    def test_allows_an_approved_operation(self, owner):
        request = request_for(SEND_OP)
        decision = ConfirmationDecision(request_id="req-1", approved=True, decided_by="owner")

        ConfirmationGate(policy_with()).ensure_approved(SEND_OP, owner, request, decision)

    @pytest.mark.security
    def test_rejects_a_user_lacking_the_permission(self, reader):
        request = request_for(SEND_OP, requested_for="reader")
        decision = ConfirmationDecision(request_id="req-1", approved=True, decided_by="reader")

        with pytest.raises(AuthorizationError):
            ConfirmationGate(policy_with()).ensure_approved(SEND_OP, reader, request, decision)

    @pytest.mark.security
    def test_permission_is_checked_before_the_confirmation_policy(self, reader):
        with pytest.raises(AuthorizationError):
            ConfirmationGate(policy_with()).ensure_approved(ARCHIVE_OP, reader, None, None)
