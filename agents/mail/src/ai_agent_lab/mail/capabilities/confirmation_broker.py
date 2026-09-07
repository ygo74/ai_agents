"""Obtention of the user's answer before a state-changing operation."""

from __future__ import annotations

from collections.abc import Callable

from ai_agent_lab.core.security.confirmation import (
    ConfirmationAuthority,
    ConfirmationDecision,
    ConfirmationLedger,
    ConfirmationRequest,
)
from ai_agent_lab.core.security.context import UserContext


class ConfirmationBroker:
    """Supplies the request and decision a gated skill needs.

    Every gated capability needs the same three steps - ask the policy, obtain
    the answer, hand both to the skill - so they are written once here.

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
