"""Deterministic confirmation policy for high-impact operations.

The rule enforced here is the one security property the language model must not
influence: whether a side effect needs an explicit human approval. The model may
propose an action, the policy decides whether it can run.

The policy is data driven so that it can be tuned per deployment and, later, per
user, without touching business code:

``always_confirm`` (per user)  >  ``auto_approve`` (per user)  >  descriptor default

Above all of that sits the security floor, and only the floor. Risk level says
how much an operation costs; the floor says what a configuration may not touch.
Letting the risk level decide both would mean that raising an operation to HIGH
- an honest description of its impact - silently took it away from the person
who owns the mailbox.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from ygo74.agent_runtime.domains.security.floor import SecurityFloor
from ygo74.agent_runtime.domains.security.operations import RiskLevel, ToolOperationDescriptor
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.errors import (
    ConfirmationMismatchError,
    ConfirmationRejectedError,
    ConfirmationRequiredError,
)

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

    def is_overridable(self, tool_name: str) -> bool:
        """Whether anybody may decide for themselves about this operation.

        An interface offering a standing answer needs to know this before it
        offers one, and only the policy can answer it.
        """
        ...


class ConfiguredConfirmationPolicy:
    """Confirmation policy combining tool defaults and user preferences."""

    def __init__(self, preference_store: ConfirmationPreferenceStore, floor: SecurityFloor) -> None:
        """Build the policy.

        The floor is required rather than defaulted. A security control with a
        permissive default is one forgotten argument away from disarming
        itself, and the omission would be invisible until an email left the
        mailbox unannounced. Pass ``SecurityFloor(())`` to mean "nothing is
        protected", so that saying it is a decision somebody wrote down.
        """
        self._preference_store = preference_store
        self._floor = floor

    def requires_confirmation(self, operation: ToolOperationDescriptor, user: UserContext) -> bool:
        """Return ``True`` when the operation must be confirmed by the user."""
        if self._floor.confirmation_is_mandatory(operation.tool_name):
            return True

        preferences = self._preference_store.preferences_for(user.user_id)
        chosen = preferences.decision_for(operation.tool_name)
        if chosen is not None:
            return chosen

        return operation.confirmation_required_by_default

    def is_overridable(self, tool_name: str) -> bool:
        """Whether a user may decide for themselves about this operation.

        Offering somebody a choice they do not have would be worse than not
        offering it, so the interface asks before proposing one.
        """
        return not self._floor.confirmation_is_mandatory(tool_name)


class ConfirmationDetail(BaseModel):
    """One labelled fact shown to the user before they decide."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1)
    value: str


class ConfirmationKey(BaseModel):
    """Identifies the operation a confirmation is about.

    Presenting a confirmation and executing the operation happen in two
    different places. The key lets both name the same thing, so the request the
    user actually saw is the one that authorises the call and the one recorded
    in the audit trail.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(min_length=1)
    target: str = ""


class ConfirmationRequest(BaseModel):
    """What the user is being asked to approve.

    The details are meant for a human decision and may contain recipients or a
    subject. They are never written to logs or traces.

    ``requested_for`` binds the request to the user it was built for, so an
    answer collected for one mailbox cannot authorise an operation on another.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    operation: ToolOperationDescriptor
    requested_for: str = Field(min_length=1)
    title: str = Field(min_length=1)
    target: str = ""
    details: tuple[ConfirmationDetail, ...] = ()

    @property
    def key(self) -> ConfirmationKey:
        """Operation this request is about."""
        return ConfirmationKey(tool_name=self.operation.tool_name, target=self.target)


class ConfirmationDecision(BaseModel):
    """The answer given by the user to a confirmation request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    approved: bool
    decided_by: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConfirmationOutcome(BaseModel):
    """A confirmation request together with the answer it received."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ConfirmationRequest
    decision: ConfirmationDecision


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


@runtime_checkable
class ConfirmationLedger(Protocol):
    """Holds the answers already collected from a user.

    An agent framework may collect the approval before it invokes the tool
    function. The ledger carries that answer, and the exact request the user was
    shown, across to the moment the operation runs.
    """

    def record(self, outcome: ConfirmationOutcome, user: UserContext) -> None:
        """Store one answered confirmation for a user."""
        ...

    def take(self, key: ConfirmationKey, user: UserContext) -> ConfirmationOutcome | None:
        """Consume the answer recorded for an operation, if any.

        An answer is consumed once, so a single approval can never authorise
        two executions.
        """
        ...

    def discard(self, user: UserContext) -> None:
        """Drop every answer recorded for a user."""
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
            PermissionDeniedError: the user lacks the required permission.
            ConfirmationRequiredError: no decision was supplied for a gated operation.
            ConfirmationRejectedError: the user declined the operation.
            ConfirmationMismatchError: the decision answers a different request,
                or the approval was not granted by this user.
        """
        user.require_permission(operation.required_permission)

        if not self._policy.requires_confirmation(operation, user):
            return

        if request is None or decision is None:
            raise ConfirmationRequiredError(operation.tool_name)

        if decision.request_id != request.request_id:
            raise ConfirmationMismatchError(request.request_id, decision.request_id)

        self._ensure_same_user(request, decision, user)

        if not decision.approved:
            raise ConfirmationRejectedError(operation.tool_name)

    @staticmethod
    def _ensure_same_user(
        request: ConfirmationRequest,
        decision: ConfirmationDecision,
        user: UserContext,
    ) -> None:
        """Refuse an approval that belongs to somebody else.

        Without this check the last line of defence would let one user's answer
        authorise an operation on another user's mailbox.
        """
        if request.requested_for != user.user_id:
            raise ConfirmationMismatchError(request.request_id, f"request issued for {request.requested_for!r}")
        if decision.decided_by != user.user_id:
            raise ConfirmationMismatchError(request.request_id, f"decision made by {decision.decided_by!r}")
