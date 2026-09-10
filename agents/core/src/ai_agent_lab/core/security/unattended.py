"""Confirmation authority for a framework that collects approvals up front.

Both agentic frameworks in use here suspend a gated tool call and ask the host
*before* they invoke the tool function: Microsoft Agent Framework through
``approval_mode="always_require"``, LangGraph through the human-in-the-loop
middleware and an interrupt. In both cases the host records the answer, together
with the exact request the user saw, in the confirmation ledger. By the time a
skill runs, the broker finds that answer and never reaches an authority at all.

Reaching this authority therefore means something went wrong: a capability was
gated by the policy but was not suspended by the framework, or its confirmation
was consumed by a different call. Rather than approve on the framework's behalf,
it refuses. Failing closed keeps a registration mistake from turning into an
unattended send.

It lives in the core because it holds no framework knowledge whatsoever, and
because every adapter needs exactly this behaviour. Copying it per framework
would be one copy away from one of them quietly approving.
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
