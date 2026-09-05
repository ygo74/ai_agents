"""Obtention of the user's answer before a state-changing operation."""

from __future__ import annotations

from ai_agent_lab.domain.security.confirmation import (
    ConfirmationAuthority,
    ConfirmationDecision,
    ConfirmationRequest,
)
from ai_agent_lab.domain.security.context import UserContext


class ConfirmationBroker:
    """Asks the confirmation authority when, and only when, the policy requires it.

    Every gated capability needs the same three steps - ask the policy, build the
    request, collect the answer - so they are written once here.
    """

    def __init__(self, authority: ConfirmationAuthority) -> None:
        self._authority = authority

    async def resolve(
        self,
        *,
        required: bool,
        request: ConfirmationRequest,
        user: UserContext,
    ) -> tuple[ConfirmationRequest | None, ConfirmationDecision | None]:
        """Return the request and decision to hand to a gated skill.

        When the policy does not require a confirmation, nothing is asked and the
        pair is empty; the skill's own gate will reach the same conclusion.
        """
        if not required:
            return None, None
        decision = await self._authority.obtain(request, user)
        return request, decision
