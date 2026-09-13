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

import logging
from collections.abc import Sequence

from ygo74.agent_runtime.domains.humanapproval.confirmation import (
    ConfirmationDecision,
    ConfirmationOutcome,
    ConfirmationPolicy,
    ConfirmationRequest,
)
from ygo74.agent_runtime.domains.humanapproval.ledger import InMemoryConfirmationLedger
from ygo74.agent_runtime.domains.security.security_errors import SecurityError
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.maf.approval import PendingToolApproval
from ai_agent_lab.mail.application.approval.resolver import ApprovalRound
from ai_agent_lab.mail.application.confirmation_presenter import MailConfirmationPresenter
from ai_agent_lab.mail.application.console import (
    ConfirmationAnswer,
    Console,
    ConsoleConfirmationPrompt,
)

_logger = logging.getLogger(__name__)


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
        _logger.info("Initializing Mail Agent console approval resolver")
        _logger.debug(
            "ConsoleApprovalResolver.__init__ arguments: presenter_type=%s, prompt_type=%s, "
            "console_type=%s, policy_type=%s, user_id=%s",
            type(presenter).__name__,
            type(prompt).__name__,
            type(console).__name__,
            type(policy).__name__,
            user.user_id,
        )
        self._presenter = presenter
        self._prompt = prompt
        self._console = console
        self._ledger = ledger
        self._policy = policy
        self._user = user
        self._standing_approvals: set[str] = set()

    def will_question(self, pending: Sequence[PendingToolApproval]) -> bool:
        """Whether this batch holds a call no standing answer already covers."""
        _logger.info("Checking whether Mail approvals require a console question")
        _logger.debug(
            "ConsoleApprovalResolver.will_question arguments: pending=%d, tool_names=%s",
            len(pending),
            tuple(approval.tool_name for approval in pending),
        )
        return any(approval.tool_name not in self._standing_approvals for approval in pending)

    async def resolve(self, pending: Sequence[PendingToolApproval]) -> ApprovalRound:
        """Ask about each call and build the answers that resume them."""
        _logger.info("Resolving Mail approval batch at the console")
        _logger.debug(
            "ConsoleApprovalResolver.resolve arguments: pending=%d, tool_names=%s, user_id=%s",
            len(pending),
            tuple(approval.tool_name for approval in pending),
            self._user.user_id,
        )
        questioned = self.will_question(pending)
        _logger.info("Starting Mail console approval decision loop")
        answers = [approval.answer(approved=await self._decide(approval)) for approval in pending]
        return ApprovalRound(answers=tuple(answers), questioned_user=questioned)

    async def _decide(self, approval: PendingToolApproval) -> bool:
        """Ask the user about one suspended call and record the answer.

        A standing answer removes the question, never the trace: each operation
        still gets its own request, its own decision and its own audit record.
        """
        _logger.debug(
            "ConsoleApprovalResolver._decide arguments: tool_name=%s, argument_names=%s, user_id=%s",
            approval.tool_name,
            tuple(sorted(approval.arguments)),
            self._user.user_id,
        )
        try:
            request = await self._presenter.present(approval.tool_name, approval.arguments, self._user)
        except (DomainError, SecurityError) as error:
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
        _logger.info("Checking standing approval eligibility")
        _logger.debug("ConsoleApprovalResolver._may_stand arguments: tool_name=%s", tool_name)
        return self._policy.is_overridable(tool_name)

    def _record(self, request: ConfirmationRequest, *, approved: bool) -> None:
        """Store the answer so the gated skill enforces this very decision."""
        _logger.info("Recording Mail console approval decision")
        _logger.debug(
            "ConsoleApprovalResolver._record arguments: request_id=%s, capability=%s, approved=%s, user_id=%s",
            request.request_id,
            request.operation.tool_name,
            approved,
            self._user.user_id,
        )
        decision = ConfirmationDecision(
            request_id=request.request_id,
            approved=approved,
            decided_by=self._user.user_id,
        )
        self._ledger.record(ConfirmationOutcome(request=request, decision=decision), self._user)
