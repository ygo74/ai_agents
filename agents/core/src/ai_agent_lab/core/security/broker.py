"""Obtention of the user's answer before a state-changing operation.

Every agent that offers a write capability needs exactly these three steps - ask
the policy, obtain the answer, hand both to the skill - and none of them involves
any single domain. The broker therefore lives in the core rather than next to one
agent: a copy per agent would be one copy away from a weaker path, and the whole
point of the confirmation machinery is that there is only one.
"""

from __future__ import annotations

from collections.abc import Callable

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfirmationAuthority,
    ConfirmationDecision,
    ConfirmationLedger,
    ConfirmationRequest,
)


class ConfirmationBroker:
    """Supplies the request and decision a gated skill needs.

    An agent framework normally collects the approval *before* it invokes the
    tool function. In that case the answer, together with the exact request the
    user was shown, is already in the ledger and is reused as is. Reusing it
    rather than minting a fresh request is what makes the audit trail refer to
    the confirmation a human actually granted.

    When nothing was collected beforehand the authority is asked directly, which
    is the path a script or a non-suspending framework takes.
    """

    def __init__(self, authority: ConfirmationAuthority, ledger: ConfirmationLedger) -> None:
        self._authority = authority
        self._ledger = ledger

    async def resolve(
        self,
        *,
        required: bool,
        build_request: Callable[[], ConfirmationRequest],
        user: UserContext,
    ) -> tuple[ConfirmationRequest | None, ConfirmationDecision | None]:
        """Return the request and decision to hand to a gated skill.

        When the policy does not require a confirmation, nothing is asked and
        the pair is empty; the skill's own gate reaches the same conclusion.
        """
        if not required:
            return None, None

        request = build_request()
        recorded = self._ledger.take(request.key, user)
        if recorded is not None:
            return recorded.request, recorded.decision

        return request, await self._authority.obtain(request, user)
