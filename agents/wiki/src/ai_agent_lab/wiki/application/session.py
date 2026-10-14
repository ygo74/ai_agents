"""Wiki approval composition around the shared native LangGraph binding.

The runtime integration owns LangGraph invocation, streaming and bounded
interrupt cleanup. This application adapter supplies only Wiki's resolver and
grant cleanup, while ``WikiAgentRuntime`` retains its identity-derived thread.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

from ygo74.agent_runtime.domains.contracts.agent_output import AgentOutput
from ygo74.agent_runtime.domains.contracts.stream_events import AgentStreamEvent
from ygo74.agent_runtime.integrations.langchain import LangGraphPendingApproval as PendingToolApproval
from ygo74.agent_runtime.integrations.langchain import LangGraphSession

from ai_agent_lab.wiki.application.composition import WikiAgentRuntime

_logger = logging.getLogger(__name__)


class ApprovalResolver(Protocol):
    """Wiki domain policy for a batch of suspended tool calls."""

    def will_question(self, pending: tuple[PendingToolApproval, ...]) -> bool:
        """Whether answering this batch puts a question to a person."""
        ...

    async def resolve(self, pending: tuple[PendingToolApproval, ...]) -> list[dict[str, Any]]:
        """Return one decision per suspended call, in the order given."""
        ...


class WikiAgentSession:
    """Provide Wiki policy to the runtime's LangGraph session binding."""

    def __init__(
        self,
        runtime: WikiAgentRuntime,
        resolver: ApprovalResolver,
        *,
        max_approval_rounds: int = 25,
        max_total_rounds: int = 200,
    ) -> None:
        self._runtime = runtime
        self._binding = LangGraphSession(
            runtime.agent,
            thread_id=runtime.thread_id,
            resolver=resolver,
            discard_authorizations=lambda: runtime.confirmation_ledger.discard(runtime.user),
            max_approval_rounds=max_approval_rounds,
            max_total_rounds=max_total_rounds,
        )

    async def ask(self, message: str) -> str:
        """Run one user turn using server-managed LangGraph history."""
        _logger.info("Starting turn for thread_id=%s (message_length=%d)", self._runtime.thread_id, len(message))
        return await self._binding.ask(message)

    async def ask_output(self, message: str) -> AgentOutput:
        """Return the binding's typed result for the runtime conversation engine."""
        return await self._binding.ask_output(message)

    def ask_stream(self, message: str) -> AsyncIterator[AgentStreamEvent]:
        """Return native neutral events for HTTP streaming surfaces."""
        return self._binding.ask_stream(message)
