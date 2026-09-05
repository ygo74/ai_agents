"""Confirmation authority used when the framework already collected the answer.

Microsoft Agent Framework invokes a gated tool function only after the user
approved the call. By the time a skill asks its authority, the answer is
therefore known.

The class stays explicit about that assumption rather than hiding it: it is
built on the same confirmation policy the adapter used to decide which tools to
register as gated, and refuses to vouch for anything that policy would not have
suspended. A registration mistake fails loudly instead of silently turning into
an unattended approval.
"""

from __future__ import annotations

from ai_agent_lab.domain.security.confirmation import (
    ConfirmationDecision,
    ConfirmationPolicy,
    ConfirmationRequest,
)
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.domain.security.errors import ConfirmationRequiredError


class FrameworkApprovalAuthority:
    """Reports the approval the agent framework already obtained."""

    def __init__(self, policy: ConfirmationPolicy) -> None:
        self._policy = policy

    async def obtain(self, request: ConfirmationRequest, user: UserContext) -> ConfirmationDecision:
        """Return the decision for a capability the framework gated."""
        if not self._policy.requires_confirmation(request.operation, user):
            raise ConfirmationRequiredError(request.operation.tool_name)
        return ConfirmationDecision(
            request_id=request.request_id,
            approved=True,
            decided_by=user.user_id,
        )

