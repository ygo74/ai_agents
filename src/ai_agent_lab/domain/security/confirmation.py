"""Deterministic confirmation policy for high-impact operations.

The rule enforced here is the one security property the language model must not
influence: whether a side effect needs an explicit human approval. The model may
propose an action, the policy decides whether it can run.

The policy is data driven so that it can be tuned per deployment and, later, per
user, without touching business code:

``always_confirm`` (per user)  >  ``auto_approve`` (per user)  >  descriptor default

A configurable risk floor sits above all of that: operations at or above
``non_overridable_risk`` always require confirmation, so a preference file can
never silently disarm sending an email.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.domain.security.errors import (
    ConfirmationMismatchError,
    ConfirmationRejectedError,
    ConfirmationRequiredError,
)
from ai_agent_lab.domain.security.operations import RiskLevel, ToolOperationDescriptor

_RISK_SEVERITY: Mapping[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
}


class ConfirmationPreferences(BaseModel):
    """Per-user tuning of the confirmation policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    auto_approved_tools: frozenset[str] = frozenset()
    always_confirm_tools: frozenset[str] = frozenset()

    def decision_for(self, tool_name: str) -> bool | None:
        """Return the user's explicit choice for a tool, if any."""
        if tool_name in self.always_confirm_tools:
            return True
        if tool_name in self.auto_approved_tools:
            return False
        return None


DEFAULT_PREFERENCES = ConfirmationPreferences()


@runtime_checkable
class ConfirmationPreferenceStore(Protocol):
    """Source of per-user confirmation preferences."""

    def preferences_for(self, user_id: str) -> ConfirmationPreferences:
        """Return the preferences of a user, defaults included."""
        ...


class InMemoryConfirmationPreferenceStore:
    """Preference store backed by a mapping, used for configuration and tests."""

    def __init__(
        self,
        preferences_by_user: Mapping[str, ConfirmationPreferences] | None = None,
        *,
        fallback: ConfirmationPreferences = DEFAULT_PREFERENCES,
    ) -> None:
        self._preferences_by_user = dict(preferences_by_user or {})
        self._fallback = fallback

    def preferences_for(self, user_id: str) -> ConfirmationPreferences:
        """Return the preferences of a user, falling back to the default set."""
        return self._preferences_by_user.get(user_id, self._fallback)

    def set_preferences(self, user_id: str, preferences: ConfirmationPreferences) -> None:
        """Replace the preferences of a user."""
        self._preferences_by_user[user_id] = preferences


@runtime_checkable
class ConfirmationPolicy(Protocol):
    """Decides whether an operation needs an explicit human approval."""

    def requires_confirmation(self, operation: ToolOperationDescriptor, user: UserContext) -> bool:
        """Return ``True`` when the operation must be confirmed by the user."""
        ...


class ConfiguredConfirmationPolicy:
    """Confirmation policy combining tool defaults and user preferences."""

    def __init__(
        self,
        preference_store: ConfirmationPreferenceStore,
        *,
        non_overridable_risk: RiskLevel = RiskLevel.HIGH,
    ) -> None:
        self._preference_store = preference_store
        self._non_overridable_severity = _RISK_SEVERITY[non_overridable_risk]

    def requires_confirmation(self, operation: ToolOperationDescriptor, user: UserContext) -> bool:
        """Return ``True`` when the operation must be confirmed by the user."""
        if _RISK_SEVERITY[operation.risk_level] >= self._non_overridable_severity:
            return True

        preferences = self._preference_store.preferences_for(user.user_id)
        chosen = preferences.decision_for(operation.tool_name)
        if chosen is not None:
            return chosen

        return operation.confirmation_required_by_default


class ConfirmationDetail(BaseModel):
    """One labelled fact shown to the user before they decide."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1)
    value: str


class ConfirmationRequest(BaseModel):
    """What the user is being asked to approve.

    The details are meant for a human decision and may contain recipients or a
    subject. They are never written to logs or traces.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    operation: ToolOperationDescriptor
    title: str = Field(min_length=1)
    details: tuple[ConfirmationDetail, ...] = ()


class ConfirmationDecision(BaseModel):
    """The answer given by the user to a confirmation request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    approved: bool
    decided_by: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class ConfirmationAuthority(Protocol):
    """Whoever is able to answer a confirmation request.

    Implementations reach the human in whatever way the runtime allows: a
    console prompt, an agent framework approval flow, a chat card. The decision
    always comes from outside the language model.
    """

    async def obtain(self, request: ConfirmationRequest, user: UserContext) -> ConfirmationDecision:
        """Return the user's answer to a confirmation request."""
        ...


class ConfirmationGate:
    """Second, framework-independent enforcement of the confirmation policy.

    The framework adapter already suspends gated tool calls. This gate makes the
    guarantee hold even when a skill is invoked directly - from another
    framework, from a script, or from a test - so the rule cannot be bypassed by
    changing the orchestration layer.
    """

    def __init__(self, policy: ConfirmationPolicy) -> None:
        self._policy = policy

    def ensure_approved(
        self,
        operation: ToolOperationDescriptor,
        user: UserContext,
        request: ConfirmationRequest | None,
        decision: ConfirmationDecision | None,
    ) -> None:
        """Raise unless the operation may proceed.

        Raises:
            ConfirmationRequiredError: no decision was supplied for a gated operation.
            ConfirmationRejectedError: the user declined the operation.
            ConfirmationMismatchError: the decision answers a different request.
        """
        user.require_permission(operation.required_permission)

        if not self._policy.requires_confirmation(operation, user):
            return

        if request is None or decision is None:
            raise ConfirmationRequiredError(operation.tool_name)

        if decision.request_id != request.request_id:
            raise ConfirmationMismatchError(request.request_id, decision.request_id)

        if not decision.approved:
            raise ConfirmationRejectedError(operation.tool_name)
