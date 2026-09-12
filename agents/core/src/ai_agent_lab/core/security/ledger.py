"""In-memory ledger of the confirmations already answered by a user.

Like :mod:`ai_agent_lab.core.security.broker`, this holds no knowledge of any
domain: it carries an answer from where a framework collected it to where the
domain enforces it. Every agent needs that carriage, so it is written once.
"""

from __future__ import annotations

from ai_agent_lab.core.security.confirmation import (
    ConfirmationKey,
    ConfirmationLedger,
    ConfirmationOutcome,
)
from ai_agent_lab.core.security.context import UserContext


class InMemoryConfirmationLedger(ConfirmationLedger):
    """Carries an answer from where it was collected to where it is enforced.

    Entries are scoped to their user and consumed once, so one approval can
    neither authorise an operation for another user nor authorise the same
    operation twice.
    """

    def __init__(self) -> None:
        self._outcomes: dict[tuple[str, ConfirmationKey], list[ConfirmationOutcome]] = {}

    def record(self, outcome: ConfirmationOutcome, user: UserContext) -> None:
        """Store one answered confirmation for a user."""
        self._outcomes.setdefault((user.user_id, outcome.request.key), []).append(outcome)

    def take(self, key: ConfirmationKey, user: UserContext) -> ConfirmationOutcome | None:
        """Consume the answer recorded for an operation, if any."""
        queue = self._outcomes.get((user.user_id, key))
        if not queue:
            return None
        outcome = queue.pop(0)
        if not queue:
            del self._outcomes[(user.user_id, key)]
        return outcome

    def discard(self, user: UserContext) -> None:
        """Drop every answer recorded for a user.

        Used when a turn is abandoned: an answer given under one premise must
        never authorise an operation during a later, unrelated turn.
        """
        for entry in [entry for entry in self._outcomes if entry[0] == user.user_id]:
            del self._outcomes[entry]

    def pending_count(self, user: UserContext) -> int:
        """How many unconsumed answers a user still has, for assertions."""
        return sum(len(queue) for (user_id, _), queue in self._outcomes.items() if user_id == user.user_id)
