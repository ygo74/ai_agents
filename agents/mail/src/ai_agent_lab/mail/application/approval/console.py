"""Answering approvals at a console, by asking the person sitting at it.

This is the behaviour the command line has always had, moved behind a port so a
second surface can answer differently without touching the session loop.

Two rules are worth restating because they are easy to lose in a refactor. The
recorded request is the one the user *read*, so the skill enforces and the audit
trail records exactly what was approved. And a capability that cannot be
described is declined rather than approved blindly: an unreadable prompt is not
a safeguard.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationOutcome,
    ConfirmationPolicy,
    ConfirmationRequest,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.maf.approval import PendingToolApproval
from ai_agent_lab.mail.application.approval.resolver import ApprovalRound
from ai_agent_lab.mail.application.confirmation_presenter import MailConfirmationPresenter
from ai_agent_lab.mail.application.console import (
    ConfirmationAnswer,
    Console,
    ConsoleConfirmationPrompt,
)
from ai_agent_lab.mail.inmemory.confirmation_ledger import InMemoryConfirmationLedger


class ConsoleApprovalResolver:
    """Puts each suspended call to the person at the console."""

    def __init__(
        self,
        presenter: MailConfirmationPresenter,
        prompt: ConsoleConfirmationPrompt,
        console: Console,
        ledger: InMemoryConfirmationLedger,
        policy: ConfirmationPolicy,
        user: UserContext,
    ) -> None:
        self._presenter = presenter
        self._prompt = prompt
        self._console = console
        self._ledger = ledger
        self._policy = policy
        self._user = user
        self._standing_approvals: set[str] = set()

    def will_question(self, pending: Sequence[PendingToolApproval]) -> bool:
        """Whether this batch holds a call no standing answer already covers."""
        return any(approval.tool_name not in self._standing_approvals for approval in pending)

    async def resolve(self, pending: Sequence[PendingToolApproval]) -> ApprovalRound:
        """Ask about each call and build the answers that resume them."""
        questioned = self.will_question(pending)
        answers = [approval.answer(approved=await self._decide(approval)) for approval in pending]
        return ApprovalRound(answers=tuple(answers), questioned_user=questioned)

    async def _decide(self, approval: PendingToolApproval) -> bool:
        """Ask the user about one suspended call and record the answer.

        A standing answer removes the question, never the trace: each operation
        still gets its own request, its own decision and its own audit record.
        """
        try:
            request = await self._presenter.present(approval.tool_name, approval.arguments, self._user)
        except DomainError as error:
            self._console.write(f"[confirmation] cannot describe {approval.tool_name}: {error}")
            self._console.write("  -> declined")
            return False

        if approval.tool_name in self._standing_approvals:
            self._record(request, approved=True)
            return True

        answer = self._prompt.ask(request, offer_all=self._may_stand(approval.tool_name))
        if answer is ConfirmationAnswer.APPROVE_ALL:
            self._standing_approvals.add(approval.tool_name)
        approved = answer is not ConfirmationAnswer.DECLINE
        self._record(request, approved=approved)
        return approved

    def _may_stand(self, tool_name: str) -> bool:
        """Whether a standing answer may be offered for this capability.

        Only the policy knows, because only the policy knows what the security
        floor protects. Offering the choice and then ignoring it would be worse
        than never offering it.
        """
        return self._policy.is_overridable(tool_name)

    def _record(self, request: ConfirmationRequest, *, approved: bool) -> None:
        """Store the answer so the gated skill enforces this very decision."""
        decision = ConfirmationDecision(
            request_id=request.request_id,
            approved=approved,
            decided_by=self._user.user_id,
        )
        self._ledger.record(ConfirmationOutcome(request=request, decision=decision), self._user)
