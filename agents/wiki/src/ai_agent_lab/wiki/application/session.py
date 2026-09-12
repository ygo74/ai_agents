"""Multi-turn conversation with the Wiki Agent, on LangGraph.

The loop is deliberately explicit about approvals: whenever the middleware
suspends a gated tool call, it is answered before anything resumes. Nothing here
decides whether an approval is needed - that came from the confirmation policy
when the interrupt table was built - and nothing here decides *how* it is
answered either. That belongs to an :class:`ApprovalResolver`, so the same loop
drives a console session and an HTTP request without knowing which it is running.

A turn is never abandoned while approvals are still outstanding. LangGraph keeps
the interrupted state under the thread identifier, so walking away from it would
leave a suspended write that a later, unrelated turn could resume under a
different premise. Whatever remains is explicitly rejected instead.

Where this differs from the Microsoft Agent Framework session is worth recording
for the comparison: the conversation state is addressed by an explicit
``thread_id`` rather than held by a session object, so resuming is a call with a
config rather than a method on something the host is holding.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ai_agent_lab.langgraph.approval import LangGraphApprovalTranslator, PendingToolApproval
from ai_agent_lab.wiki.application.composition import WikiAgentRuntime

_MAX_ASKED_ROUNDS = 25
_MAX_TOTAL_ROUNDS = 200

_logger = logging.getLogger(__name__)

_INTERRUPTED = (
    "The request asked for too many approvals in a row, so it was interrupted. "
    "Everything still pending was declined and nothing was changed."
)

_EXHAUSTED = (
    "The request needed more tool calls than one turn allows, so it was interrupted. "
    "Everything still pending was declined and nothing was changed. "
    "Ask for a smaller batch."
)


class ApprovalResolver(Protocol):
    """Decides what to answer to a batch of suspended tool calls."""

    def will_question(self, pending: tuple[PendingToolApproval, ...]) -> bool:
        """Whether answering this batch puts a question to a person."""
        ...

    async def resolve(self, pending: tuple[PendingToolApproval, ...]) -> list[dict[str, Any]]:
        """Return one decision per suspended call, in the order given."""
        ...


class WikiAgentSession:
    """Drives one conversation with the Wiki Agent."""

    def __init__(
        self,
        runtime: WikiAgentRuntime,
        resolver: ApprovalResolver,
        translator: LangGraphApprovalTranslator,
        *,
        max_approval_rounds: int = _MAX_ASKED_ROUNDS,
        max_total_rounds: int = _MAX_TOTAL_ROUNDS,
    ) -> None:
        self._runtime = runtime
        self._resolver = resolver
        self._translator = translator
        self._max_asked_rounds = max_approval_rounds
        self._max_total_rounds = max_total_rounds

    @property
    def _config(self) -> dict[str, Any]:
        """The configuration addressing this conversation's persisted state."""
        return {"configurable": {"thread_id": self._runtime.thread_id}}

    async def ask(self, message: str) -> str:
        """Run one user turn, resolving any approval the middleware requests.

        Two budgets, because they guard different things. The first counts the
        rounds that actually put a question to the user: a request that
        interrogates somebody twenty-five times has gone wrong whatever it is
        doing. The second is a ceiling on rounds of any kind, so a runaway loop
        still ends.
        """
        result = await self._runtime.agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config=self._config,
        )
        asked = 0
        for _ in range(self._max_total_rounds):
            pending = self._pending_of(result)
            if not pending:
                return self._text_of(result)
            if self._resolver.will_question(pending):
                asked += 1
                if asked > self._max_asked_rounds:
                    return await self._abandon(result, _INTERRUPTED)
            result = await self._resume(pending)
        return await self._abandon(result, _EXHAUSTED)

    def _pending_of(self, result: Any) -> tuple[PendingToolApproval, ...]:
        """Every tool call the middleware suspended in this result."""
        return self._translator.pending_approvals(self._interrupts_of(result))

    @staticmethod
    def _interrupts_of(result: Any) -> tuple[Any, ...]:
        """Read the interrupts out of whichever shape the graph returned.

        ``ainvoke`` hands back a mapping carrying ``__interrupt__`` unless the
        caller asked for the newer output object, which exposes ``interrupts``.
        Both are read so the session does not depend on that choice.
        """
        carried = getattr(result, "interrupts", None)
        if carried:
            return tuple(carried)
        if isinstance(result, dict):
            return tuple(result.get("__interrupt__") or ())
        return ()

    async def _resume(self, pending: tuple[PendingToolApproval, ...]) -> Any:
        """Collect the user's answers and let the graph continue."""
        decisions = await self._resolver.resolve(pending)
        return await self._runtime.agent.ainvoke(
            self._translator.resume_command(decisions),
            config=self._config,
        )

    async def _abandon(self, result: Any, reason: str) -> str:
        """Leave a turn without letting anything pending execute.

        Everything still suspended is rejected. Simply walking away would leave
        the graph interrupted under this thread, and the next turn would resume
        a batch the user was told had been abandoned.

        The confirmation ledger is emptied for the same reason. An answer given
        under one premise must never authorise an operation during a later,
        unrelated turn, and an approval collected for a call that was then
        abandoned is exactly such an answer.
        """
        self._runtime.confirmation_ledger.discard(self._runtime.user)
        current = result
        for _ in range(self._max_asked_rounds):
            pending = self._pending_of(current)
            if not pending:
                return reason
            answers = [approval.answer(approved=False) for approval in pending]
            try:
                current = await self._runtime.agent.ainvoke(
                    self._translator.resume_command(answers),
                    config=self._config,
                )
            except Exception as error:  # noqa: BLE001 - see the docstring
                _logger.warning("could not finish declining an abandoned turn: %s", type(error).__name__)
                return reason
        return reason

    @staticmethod
    def _text_of(result: Any) -> str:
        """Return the assistant's answer of a finished turn."""
        values = getattr(result, "value", result)
        messages = values.get("messages", []) if isinstance(values, dict) else []
        for message in reversed(messages):
            content = getattr(message, "content", "")
            if content and getattr(message, "type", "") == "ai":
                return str(content)
        return ""
