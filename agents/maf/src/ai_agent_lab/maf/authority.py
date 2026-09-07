"""Confirmation authority for a framework that collects approvals up front.

Microsoft Agent Framework suspends a gated tool call and asks the host before it
invokes the tool function. The host records the answer, together with the exact
request the user saw, in the confirmation ledger. By the time a skill runs, the
broker finds that answer and never reaches an authority at all.

Reaching this authority therefore means something went wrong: a capability was
gated by the policy but was not suspended by the framework, or its confirmation
was consumed by a different call. Rather than approve on the framework's behalf,
it refuses. Failing closed keeps a registration mistake from turning into an
unattended send.
"""

from __future__ import annotations

from ai_agent_lab.core.security.confirmation import ConfirmationDecision, ConfirmationRequest
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.errors import ConfirmationRequiredError


class UnattendedApprovalAuthority:
    """Refuses to answer on behalf of an absent user."""

    async def obtain(self, request: ConfirmationRequest, user: UserContext) -> ConfirmationDecision:
        """Never approve: no human answered this request.

        Raises:
            ConfirmationRequiredError: always.
        """
        del user
        raise ConfirmationRequiredError(request.operation.tool_name)
