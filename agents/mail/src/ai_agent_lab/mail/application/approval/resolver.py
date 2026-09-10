"""How a suspended tool call gets its answer.

The framework decides *that* a call must be approved; this decides *who answers
and how*. Those are different questions, and separating them is what lets the
same agent run on two surfaces.

At a console, the question is put to the person and the turn waits. Over HTTP
there is nobody to wait for: a request/response API has no side channel, so the
turn must end and the answer arrive in a later one. Both surfaces record the very
decision the user gave, in the same ledger, and both stay under the same security
floor - only the conversation differs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agent_framework import Content

from ai_agent_lab.maf.approval import PendingToolApproval


@dataclass(frozen=True, slots=True)
class ApprovalRound:
    """The outcome of answering one batch of suspended calls.

    Attributes:
        answers: One framework answer per pending call, in the order received.
            The framework runs a batch only once every call in it is answered,
            so a partial round would leave approved calls waiting to execute.
        questioned_user: Whether this round actually put a question to a person.
            A turn that interrogates somebody twenty-five times has gone wrong,
            but a turn answered from a standing decision or deferred to a ticket
            has asked nothing and must not be charged for it.
    """

    answers: tuple[Content, ...]
    questioned_user: bool


@runtime_checkable
class ApprovalResolver(Protocol):
    """Answers the tool calls a framework suspended."""

    def will_question(self, pending: Sequence[PendingToolApproval]) -> bool:
        """Whether resolving this batch would put a question to a person.

        Asked before resolving, so a turn can be abandoned *before* adding to
        somebody's fatigue rather than after.
        """
        ...

    async def resolve(self, pending: Sequence[PendingToolApproval]) -> ApprovalRound:
        """Answer every suspended call, recording each decision as it is made."""
        ...
