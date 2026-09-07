"""Multi-turn conversation with the Mail Agent.

The loop is deliberately explicit about approvals: whenever the framework
suspends a gated tool call, the user is asked before anything resumes. Nothing
here decides whether an approval is needed; that came from the confirmation
policy when the tools were registered.

A turn is never abandoned while approvals are still outstanding. The framework
keeps queued approval requests in the session state, so walking away from them
would let a later, unrelated turn replay answers the user gave under a different
premise. Whatever remains is explicitly declined instead.
"""

from __future__ import annotations

from typing import Any

from agent_framework import AgentResponse, AgentSession

from ai_agent_lab.application.mail.composition import MailAgentRuntime
from ai_agent_lab.application.mail.console import Console, ConsoleConfirmationPrompt
from ai_agent_lab.domain.errors import DomainError
from ai_agent_lab.domain.security.confirmation import (
    ConfirmationDecision,
    ConfirmationOutcome,
    ConfirmationRequest,
)
from ai_agent_lab.frameworks.microsoft_agent_framework.approval import (
    MafApprovalTranslator,
    PendingToolApproval,
)

_MAX_APPROVAL_ROUNDS = 25
_MAX_DECLINE_ROUNDS = 25

_INTERRUPTED = (
    "The request asked for too many approvals in a row, so it was interrupted. "
    "Everything still pending was declined and nothing was changed."
)


class MailAgentSession:
    """Drives one conversation with the Mail Agent."""

    def __init__(
        self,
        runtime: MailAgentRuntime,
        console: Console,
        prompt: ConsoleConfirmationPrompt,
        translator: MafApprovalTranslator,
        *,
        max_approval_rounds: int = _MAX_APPROVAL_ROUNDS,
    ) -> None:
        self._runtime = runtime
        self._console = console
        self._prompt = prompt
        self._translator = translator
        self._max_approval_rounds = max_approval_rounds
        self._session: AgentSession = runtime.agent.create_session(session_id=runtime.user.session_id)

    async def ask(self, message: str) -> str:
        """Run one user turn, resolving any approval the framework requests."""
        response = await self._runtime.agent.run(message, session=self._session)
        for _ in range(self._max_approval_rounds):
            pending = self._translator.pending_approvals(response)
            if not pending:
                return response.text
            response = await self._resume(pending)
        await self._decline_everything(response)
        return _INTERRUPTED

    async def _resume(self, pending: tuple[PendingToolApproval, ...]) -> AgentResponse[Any]:
        """Collect the user's answers and let the framework continue."""
        answers = [approval.answer(approved=self._decide(approval)) for approval in pending]
        return await self._runtime.agent.run(
            self._translator.answer_message(answers),
            session=self._session,
        )

    async def _decline_everything(self, response: AgentResponse[Any]) -> None:
        """Abandon a turn without leaving anything executable behind.

        The framework does not run a batch of gated calls until every one of
        them has been answered, and it keeps the answers already given in the
        session. Simply refusing what is left would complete the batch and run
        the calls approved earlier, during a turn the user was told had been
        interrupted.

        So the recorded answers are dropped first. When the batch does complete,
        the skills find no decision, the domain gate refuses, and every call
        fails closed and is audited as blocked.
        """
        self._runtime.confirmation_ledger.discard(self._runtime.user)

        current = response
        for _ in range(_MAX_DECLINE_ROUNDS):
            pending = self._translator.pending_approvals(current)
            if not pending:
                return
            answers = [approval.answer(approved=False) for approval in pending]
            current = await self._runtime.agent.run(
                self._translator.answer_message(answers),
                session=self._session,
            )
            self._runtime.confirmation_ledger.discard(self._runtime.user)

    def _decide(self, approval: PendingToolApproval) -> bool:
        """Ask the user about one suspended call and record the answer.

        The recorded request is the one the user read, so the skill enforces and
        the audit trail records exactly what was approved.

        A capability that cannot be described is refused rather than approved
        blindly.
        """
        try:
            request = self._runtime.presenter.present(approval.tool_name, approval.arguments, self._runtime.user)
        except DomainError as error:
            self._console.write(f"[confirmation] cannot describe {approval.tool_name}: {error}")
            self._console.write("  -> declined")
            return False

        approved = self._prompt.ask(request)
        self._record(request, approved=approved)
        return approved

    def _record(self, request: ConfirmationRequest, *, approved: bool) -> None:
        """Store the answer so the gated skill enforces this very decision."""
        decision = ConfirmationDecision(
            request_id=request.request_id,
            approved=approved,
            decided_by=self._runtime.user.user_id,
        )
        self._runtime.confirmation_ledger.record(
            ConfirmationOutcome(request=request, decision=decision),
            self._runtime.user,
        )
