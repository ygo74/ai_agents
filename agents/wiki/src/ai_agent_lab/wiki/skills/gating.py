"""Execution of the wiki operations that change external state.

Searching, summarising and answering are harmless; creating, replacing, deleting
and commenting are not. Everything those operations share - permission check,
confirmation policy, audit record - lives here so that no write skill can forget
a step, and so that adding a new write capability cannot introduce a different,
weaker path.

This is the wiki counterpart of :mod:`ai_agent_lab.mail.skills.gating`, and it is
deliberately shaped the same way. The two agents run on different frameworks; the
guarantee they owe a user does not depend on which.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from ai_agent_lab.core.security.audit import AuditOutcome, AuditRecord, AuditTrail
from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationDetail,
    ConfirmationGate,
    ConfirmationPolicy,
    ConfirmationRequest,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.errors import ConfirmationRejectedError, SecurityError
from ai_agent_lab.core.security.operations import ToolOperationDescriptor
from ai_agent_lab.wiki.catalog import WikiOperations, WikiToolName

ResultT = TypeVar("ResultT")


class GatedWikiOperationRunner:
    """Runs a state-changing wiki operation under the confirmation policy.

    The posture comes from :class:`WikiOperations`, the same source the framework
    adapter reads. Consulting a different one would let a capability be both
    never asked about and always refused: impossible to perform, and reported to
    the user as the wiki having refused.
    """

    def __init__(
        self,
        operations: WikiOperations,
        policy: ConfirmationPolicy,
        gate: ConfirmationGate,
        audit: AuditTrail,
    ) -> None:
        self._operations = operations
        self._policy = policy
        self._gate = gate
        self._audit = audit

    def requires_confirmation(self, tool: WikiToolName, user: UserContext) -> bool:
        """Whether the user must approve this operation before it runs."""
        return self._policy.requires_confirmation(self._operations.descriptor(tool), user)

    def build_confirmation_request(
        self,
        tool: WikiToolName,
        user: UserContext,
        title: str,
        *,
        target: str = "",
        details: Sequence[ConfirmationDetail] = (),
    ) -> ConfirmationRequest:
        """Build the request shown to the user before they decide."""
        return ConfirmationRequest(
            request_id=f"cfm-{uuid.uuid4().hex[:12]}",
            operation=self._operations.descriptor(tool),
            requested_for=user.user_id,
            title=title,
            target=target,
            details=tuple(details),
        )

    async def execute(
        self,
        tool: WikiToolName,
        user: UserContext,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        target_id: str | None = None,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> ResultT:
        """Authorise, run and audit one state-changing operation."""
        descriptor = self._operations.descriptor(tool)
        try:
            self._gate.ensure_approved(descriptor, user, request, decision)
        except SecurityError as error:
            outcome = (
                AuditOutcome.DECLINED if isinstance(error, ConfirmationRejectedError) else AuditOutcome.BLOCKED
            )
            self._write(descriptor, user, outcome, target_id, request, error)
            raise

        try:
            result = await operation()
        except Exception as error:
            self._write(descriptor, user, AuditOutcome.FAILED, target_id, request, error)
            raise

        self._write(descriptor, user, AuditOutcome.EXECUTED, target_id, request, None)
        return result

    def _write(
        self,
        descriptor: ToolOperationDescriptor,
        user: UserContext,
        outcome: AuditOutcome,
        target_id: str | None,
        request: ConfirmationRequest | None,
        error: Exception | None,
    ) -> None:
        """Append one record to the audit trail.

        The record names the operation, its outcome and the page it touched. It
        never carries a page title or body: an audit trail is read by people who
        are not necessarily entitled to the content of the page it mentions.
        """
        self._audit.record(
            AuditRecord(
                tool_name=descriptor.tool_name,
                operation_type=descriptor.operation_type,
                risk_level=descriptor.risk_level,
                outcome=outcome,
                user_id=user.user_id,
                session_id=user.session_id,
                target_id=target_id,
                confirmation_request_id=None if request is None else request.request_id,
                error_type=None if error is None else type(error).__name__,
            )
        )
