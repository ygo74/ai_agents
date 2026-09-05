"""Confirmation authority used when the framework already collected the answer.

Microsoft Agent Framework invokes a gated tool function only after the user
approved the call. By the time a skill asks its authority, the answer is
therefore known.

The class stays explicit about that assumption rather than hiding it: it is
constructed with the set of capabilities the adapter really registered as
gated, and refuses to vouch for anything else. A registration mistake fails
loudly instead of silently turning into an unattended approval.
"""

from __future__ import annotations

from collections.abc import Iterable

from ai_agent_lab.domain.security.confirmation import (
    ConfirmationDecision,
    ConfirmationRequest,
)
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.domain.security.errors import ConfirmationRequiredError


class FrameworkApprovalAuthority:
    """Reports the approval the agent framework already obtained."""

    def __init__(self, gated_tool_names: Iterable[str]) -> None:
        self._gated_tool_names = frozenset(gated_tool_names)

    async def obtain(self, request: ConfirmationRequest, user: UserContext) -> ConfirmationDecision:
        """Return the decision for a capability the framework gated."""
        if request.operation.tool_name not in self._gated_tool_names:
            raise ConfirmationRequiredError(request.operation.tool_name)
        return ConfirmationDecision(
            request_id=request.request_id,
            approved=True,
            decided_by=user.user_id,
        )
