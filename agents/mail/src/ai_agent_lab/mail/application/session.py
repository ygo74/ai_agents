"""Multi-turn conversation with the Mail Agent.

The loop is deliberately explicit about approvals: whenever the framework
suspends a gated tool call, it is answered before anything resumes. Nothing here
decides whether an approval is needed - that came from the confirmation policy
when the tools were registered - and nothing here decides *how* it is answered
either. That belongs to an :class:`ApprovalResolver`, so the same loop drives a
console session and an HTTP request without knowing which it is running.

A turn is never abandoned while approvals are still outstanding. The framework
keeps queued approval requests in the session state, so walking away from them
would let a later, unrelated turn replay answers the user gave under a different
premise. Whatever remains is explicitly declined instead.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_framework import AgentResponse, AgentSession

from ai_agent_lab.maf.approval import (
    MafApprovalTranslator,
    PendingToolApproval,
)
from ai_agent_lab.mail.application.approval.resolver import ApprovalResolver
from ai_agent_lab.mail.application.composition import MailAgentRuntime

_MAX_ASKED_ROUNDS = 25
_MAX_TOTAL_ROUNDS = 200
_MAX_DECLINE_ROUNDS = 25

_logger = logging.getLogger(__name__)

_INTERRUPTED = (
    "The request asked for too many approvals in a row, so it was interrupted. "
    "Everything still pending was declined and nothing was changed. "
    "Answering 'a' at a confirmation approves every further operation of that kind "
    "for the rest of the conversation, which avoids the interruption."
)

_EXHAUSTED = (
    "The request needed more tool calls than one turn allows, so it was interrupted. "
    "Everything still pending was declined and nothing was changed. "
    "Ask for a smaller batch."
)


class MailAgentSession:
    """Drives one conversation with the Mail Agent."""

    def __init__(
        self,
        runtime: MailAgentRuntime,
        resolver: ApprovalResolver,
        translator: MafApprovalTranslator,
        *,
        max_approval_rounds: int = _MAX_ASKED_ROUNDS,
        max_total_rounds: int = _MAX_TOTAL_ROUNDS,
    ) -> None:
        self._runtime = runtime
        self._resolver = resolver
        self._translator = translator
        self._max_asked_rounds = max_approval_rounds
        self._max_total_rounds = max_total_rounds
        self._session: AgentSession = runtime.agent.create_session(session_id=runtime.user.session_id)

    async def ask(self, message: str) -> str:
        """Run one user turn, resolving any approval the framework requests.

        Two budgets, because they guard different things. The first counts the
        rounds that actually put a question to the user: a request that
        interrogates somebody twenty-five times has gone wrong whatever it is
        doing. The second is a ceiling on rounds of any kind, so a runaway loop
        still ends.

        Counting them together would have made a standing answer worthless -
        the user says "yes to all of these", the questions stop, and the turn is
        interrupted anyway for having asked too much.
        """
        response = await self._runtime.agent.run(message, session=self._session)
        asked = 0
        for _ in range(self._max_total_rounds):
            pending = self._translator.pending_approvals(response)
            if not pending:
                return response.text
            if self._resolver.will_question(pending):
                asked += 1
                if asked > self._max_asked_rounds:
                    return await self._abandon(response, _INTERRUPTED)
            response = await self._resume(pending)
        return await self._abandon(response, _EXHAUSTED)

    async def _abandon(self, response: AgentResponse[Any], reason: str) -> str:
        """Leave a turn without letting anything pending execute."""
        await self._decline_everything(response)
        return reason

    async def _resume(self, pending: tuple[PendingToolApproval, ...]) -> AgentResponse[Any]:
        """Collect the user's answers and let the framework continue."""
        round_ = await self._resolver.resolve(pending)
        return await self._runtime.agent.run(
            self._translator.answer_message(round_.answers),
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

        The model provider may itself fail while this unwinds - a long, partly
        answered batch is exactly the conversation state it is least happy with.
        That failure is survivable and must not propagate: the ledger is already
        empty, so nothing pending can execute whether or not the batch ever
        completes. Insisting would turn a safe abandonment into a crash.
        """
        self._runtime.confirmation_ledger.discard(self._runtime.user)

        current = response
        for _ in range(_MAX_DECLINE_ROUNDS):
            pending = self._translator.pending_approvals(current)
            if not pending:
                return
            answers = [approval.answer(approved=False) for approval in pending]
            try:
                current = await self._runtime.agent.run(
                    self._translator.answer_message(answers),
                    session=self._session,
                )
            except Exception as error:  # noqa: BLE001 - see the docstring: nothing can execute now
                _logger.warning("could not finish declining an abandoned turn: %s", type(error).__name__)
                return
            finally:
                self._runtime.confirmation_ledger.discard(self._runtime.user)
