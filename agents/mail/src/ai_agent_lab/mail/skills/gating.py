"""Execution of the mail operations that change external state.

Search, summarisation and classification are harmless; sending, archiving and
labelling are not. Everything those operations share - permission check,
confirmation policy, audit record - lives here so that no write skill can
forget a step, and so that adding a new write capability cannot introduce a
different, weaker path.
"""

from __future__ import annotations

import logging
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
from ai_agent_lab.mail.catalog import MailOperations, MailToolName

ResultT = TypeVar("ResultT")
_logger = logging.getLogger(__name__)


class GatedMailOperationRunner:
    """Runs a state-changing mail operation under the confirmation policy.

    The posture comes from :class:`MailOperations`, the same source the
    framework adapter reads. Consulting a different one would let a capability
    be both never asked about and always refused.
    """

    def __init__(
        self,
        operations: MailOperations,
        policy: ConfirmationPolicy,
        gate: ConfirmationGate,
        audit: AuditTrail,
    ) -> None:
        _logger.info("Initializing gated Mail operation runner")
        _logger.debug(
            "GatedMailOperationRunner.__init__ arguments: operations_type=%s, "
            "policy_type=%s, gate_type=%s, audit_type=%s",
            type(operations).__name__,
            type(policy).__name__,
            type(gate).__name__,
            type(audit).__name__,
        )
        self._operations = operations
        self._policy = policy
        self._gate = gate
        self._audit = audit

    def requires_confirmation(self, tool: MailToolName, user: UserContext) -> bool:
        """Whether the user must approve this operation before it runs."""
        _logger.info("Checking gated Mail operation confirmation requirement")
        _logger.debug(
            "GatedMailOperationRunner.requires_confirmation arguments: tool_name=%s, user_id=%s",
            tool.value,
            user.user_id,
        )
        return self._policy.requires_confirmation(self._operations.descriptor(tool), user)

    def build_confirmation_request(
        self,
        tool: MailToolName,
        user: UserContext,
        title: str,
        *,
        target: str = "",
        details: Sequence[ConfirmationDetail] = (),
    ) -> ConfirmationRequest:
        """Build the request shown to the user before they decide."""
        _logger.info("Building gated Mail operation confirmation request")
        _logger.debug(
            "GatedMailOperationRunner.build_confirmation_request arguments: "
            "tool_name=%s, user_id=%s, title_length=%d, target=%s, details=%d",
            tool.value,
            user.user_id,
            len(title),
            target,
            len(details),
        )
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
        tool: MailToolName,
        user: UserContext,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        target_id: str | None = None,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> ResultT:
        """Authorise, run and audit one state-changing operation."""
        _logger.info("Executing gated Mail operation")
        _logger.debug(
            "GatedMailOperationRunner.execute arguments: tool_name=%s, user_id=%s, "
            "session_id=%s, operation_type=%s, target_id=%s, request_id=%s, "
            "decision_present=%s",
            tool.value,
            user.user_id,
            user.session_id,
            type(operation).__name__,
            target_id,
            None if request is None else request.request_id,
            decision is not None,
        )
        descriptor = self._operations.descriptor(tool)
        try:
            self._gate.ensure_approved(descriptor, user, request, decision)
        except SecurityError as error:
            outcome = AuditOutcome.DECLINED if isinstance(error, ConfirmationRejectedError) else AuditOutcome.BLOCKED
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
        """Append one record to the audit trail."""
        _logger.info("Writing Mail operation audit record")
        _logger.debug(
            "GatedMailOperationRunner._write arguments: tool_name=%s, user_id=%s, "
            "session_id=%s, outcome=%s, target_id=%s, request_id=%s, error_type=%s",
            descriptor.tool_name,
            user.user_id,
            user.session_id,
            outcome.value,
            target_id,
            None if request is None else request.request_id,
            None if error is None else type(error).__name__,
        )
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
