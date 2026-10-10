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
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from agent_framework import AgentResponse, AgentResponseUpdate, AgentSession, Message, ResponseStream
from ygo74.agent_runtime.domains.contracts.stream_events import AgentStreamEvent
from ygo74.agent_runtime.domains.humanapproval.approval_loop import ApprovalLoop

from ai_agent_lab.maf.approval import (
    MafApprovalTranslator,
    PendingToolApproval,
)
from ai_agent_lab.maf.streaming import MafStreamEventTranslator
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
        stream_translator: MafStreamEventTranslator | None = None,
        max_approval_rounds: int = _MAX_ASKED_ROUNDS,
        max_total_rounds: int = _MAX_TOTAL_ROUNDS,
    ) -> None:
        _logger.info("Initializing Mail Agent conversation session")
        _logger.debug(
            "MailAgentSession.__init__ arguments: session_id=%s, user_id=%s, "
            "resolver_type=%s, translator_type=%s, max_approval_rounds=%d, max_total_rounds=%d",
            runtime.user.session_id,
            runtime.user.user_id,
            type(resolver).__name__,
            type(translator).__name__,
            max_approval_rounds,
            max_total_rounds,
        )
        self._runtime = runtime
        self._resolver = resolver
        self._translator = translator
        self._max_approval_rounds = max_approval_rounds
        self._max_total_rounds = max_total_rounds
        self._stream_translator = stream_translator or MafStreamEventTranslator()
        self._session: AgentSession = runtime.agent.create_session(session_id=runtime.user.session_id)
        self._approval_loop = ApprovalLoop(
            self,
            max_approval_rounds=max_approval_rounds,
            max_total_rounds=max_total_rounds,
            max_decline_rounds=_MAX_DECLINE_ROUNDS,
            interrupted_message=_INTERRUPTED,
            exhausted_message=_EXHAUSTED,
        )

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
        _logger.info("Starting Mail Agent turn and approval loop")
        _logger.debug(
            "MailAgentSession.ask arguments: session_id=%s, user_id=%s, message_length=%d",
            self._runtime.user.session_id,
            self._runtime.user.user_id,
            len(message),
        )
        response = await self._runtime.agent.run(message, session=self._session)
        return await self._approval_loop.run(response)

    async def ask_stream(self, message: str) -> AsyncIterator[AgentStreamEvent]:
        """Stream visible text while retaining the bounded approval lifecycle."""
        _logger.info("Starting streamed Mail Agent turn and approval loop")
        _logger.debug(
            "MailAgentSession.ask_stream arguments: session_id=%s, user_id=%s, message_length=%d",
            self._runtime.user.session_id,
            self._runtime.user.user_id,
            len(message),
        )
        asked = 0
        current_message: str | Message = message
        state: AgentResponse[Any] | None = None

        for _ in range(self._max_total_rounds):
            response_stream = self._stream_run(current_message)
            async for event in self._stream_translator.translate(
                response_stream,
                content_id=uuid4().hex,
            ):
                yield event
            state = await response_stream.get_final_response()
            pending = self.pending(state)
            if not pending:
                return

            asked, limit_reached = self._approval_limit_reached(pending, asked)
            if limit_reached:
                async for event in self._abandon_stream(state, _INTERRUPTED):
                    yield event
                return

            round_ = await self._resolver.resolve(pending)
            current_message = self._translator.answer_message(round_.answers)

        if state is not None:
            async for event in self._abandon_stream(state, _EXHAUSTED):
                yield event

    def _stream_run(self, message: str | Message) -> ResponseStream[AgentResponseUpdate, AgentResponse[Any]]:
        """Start one framework round in streaming mode."""
        return self._runtime.agent.run(message, stream=True, session=self._session)

    def _approval_limit_reached(
        self,
        pending: tuple[PendingToolApproval, ...],
        asked: int,
    ) -> tuple[int, bool]:
        """Count confirmation prompts and identify when their configured bound is crossed."""
        if not self.will_question(pending):
            return asked, False
        asked += 1
        return asked, asked > self._max_approval_rounds

    async def _abandon_stream(
        self,
        state: AgentResponse[Any],
        message: str,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Decline remaining calls within a bound before emitting the interruption."""
        self.discard_authorizations()
        current = state
        for _ in range(_MAX_DECLINE_ROUNDS):
            pending = self.pending(current)
            if not pending:
                yield self._stream_translator.complete_text(message, content_id=uuid4().hex)
                return
            try:
                current = await self.decline(pending)
            except Exception as error:  # noqa: BLE001 - grants are already discarded
                _logger.warning("could not finish declining an abandoned streamed turn: %s", type(error).__name__)
                yield self._stream_translator.complete_text(message, content_id=uuid4().hex)
                return
            finally:
                self.discard_authorizations()
        yield self._stream_translator.complete_text(message, content_id=uuid4().hex)

    def pending(self, response: AgentResponse[Any]) -> tuple[PendingToolApproval, ...]:
        """Inspect Microsoft Agent Framework state for suspended calls."""
        return self._translator.pending_approvals(response)

    def will_question(self, pending: tuple[PendingToolApproval, ...]) -> bool:
        """Delegate question classification to the application resolver."""
        return self._resolver.will_question(pending)

    async def resume(self, pending: tuple[PendingToolApproval, ...]) -> AgentResponse[Any]:
        """Resolve approvals and resume the framework session."""
        round_ = await self._resolver.resolve(pending)
        return await self._runtime.agent.run(
            self._translator.answer_message(round_.answers),
            session=self._session,
        )

    async def decline(self, pending: tuple[PendingToolApproval, ...]) -> AgentResponse[Any]:
        """Refuse a batch of remaining calls in framework-native form."""
        answers = [approval.answer(approved=False) for approval in pending]
        return await self._runtime.agent.run(
            self._translator.answer_message(answers),
            session=self._session,
        )

    def discard_authorizations(self) -> None:
        """Purge recorded grants before or during abandonment cleanup."""
        self._runtime.confirmation_ledger.discard(self._runtime.user)

    def final_text(self, response: AgentResponse[Any]) -> str:
        """Extract the final response text from Microsoft Agent Framework."""
        return response.text
