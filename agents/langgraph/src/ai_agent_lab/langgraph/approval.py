"""Translation between LangGraph interrupts and domain confirmations.

LangChain's human-in-the-loop middleware suspends a tool call listed in
``interrupt_on`` and reports it through ``GraphOutput.interrupts``. The host
answers with ``Command(resume={"decisions": [...]})``.

This module converts those framework payloads into the vocabulary the
application already uses, so the console, an HTTP surface and the domain gate all
speak about the same thing. It is the LangGraph counterpart of
``ai_agent_lab.maf.approval``, and it is deliberately shaped the same way.

Which capability is gated is decided by the deterministic
:class:`ConfirmationPolicy`, evaluated for the user the agent acts for. The
language model is never consulted about it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from langchain.agents.middleware import InterruptOnConfig
from langchain.agents.middleware.human_in_the_loop import DecisionType
from langgraph.types import Command
from ygo74.agent_runtime.domains.contracts.capability_registry import SkillRegistry
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationPolicy,
    ConfirmationRequest,
)

_logger = logging.getLogger(__name__)

# The only two answers a gated capability accepts.
#
# `edit` is excluded on purpose. It lets the human change the arguments *after*
# the confirmation was granted, while the ledger records the approval against the
# exact request the user was shown (`ConfirmationRequest.key`). Accepting an edit
# would run arguments nobody confirmed, which is a confirmation bypass wearing
# the costume of a feature.
#
# `respond` is excluded for a different reason: its message is delivered to the
# model as a *successful* tool result. On an operation with side effects, a
# refusal would then be indistinguishable from the operation having happened.
ALLOWED_DECISIONS: tuple[DecisionType, ...] = ("approve", "reject")

APPROVE: DecisionType = "approve"
REJECT: DecisionType = "reject"


class PendingToolApproval:
    """One suspended tool call waiting for the user's answer."""

    def __init__(self, action: Mapping[str, Any]) -> None:
        self._action = action

    @property
    def tool_name(self) -> str:
        """Name of the capability the model wants to run."""
        return str(self._action.get("name", ""))

    @property
    def arguments(self) -> Mapping[str, Any]:
        """Arguments the model proposed, always a mapping."""
        raw = self._action.get("args")
        return dict(raw) if isinstance(raw, Mapping) else {}

    def answer(self, *, approved: bool) -> dict[str, Any]:
        """Build the framework decision carrying the user's answer."""
        if approved:
            return {"type": APPROVE}
        return {"type": REJECT, "message": "The user declined this operation."}


class LangGraphApprovalTranslator:
    """Builds the interrupt policy, reads interrupts and answers them."""

    def interrupt_on(
        self,
        definition: SkillRegistry,
        policy: ConfirmationPolicy,
        user: UserContext,
    ) -> dict[str, bool | InterruptOnConfig]:
        """Map the confirmation policy onto the middleware configuration.

        Every capability is named explicitly, including the ungated ones. A
        capability missing from this mapping is simply not interrupted, so
        listing only the gated ones would make a typo silently ungate an
        operation instead of failing.
        """
        table = {
            descriptor.tool_name: self._entry(policy.requires_confirmation(descriptor.operation, user))
            for descriptor in definition.skills
        }
        gated = [k for k, v in table.items() if v is not False]
        _logger.info("Configured interrupt policy: %d total tools, %d gated (%s)", len(table), len(gated), gated)
        _logger.debug("Interrupt configuration table: %s", {k: bool(v) for k, v in table.items()})
        return table

    @staticmethod
    def _entry(gated: bool) -> bool | InterruptOnConfig:
        """Return the middleware entry of one capability."""
        if not gated:
            return False
        return InterruptOnConfig(allowed_decisions=list(ALLOWED_DECISIONS))

    def pending_approvals(self, interrupts: Sequence[Any]) -> tuple[PendingToolApproval, ...]:
        """Every tool call the framework suspended in this response."""
        approvals = tuple(
            PendingToolApproval(action) for interrupt in interrupts for action in self._action_requests(interrupt)
        )
        if approvals:
            _logger.info("Found %d pending tool approval(s) in interrupt payload", len(approvals))
            _logger.debug("Pending approvals summary: %s", [(a.tool_name, a.arguments) for a in approvals])
        return approvals

    @staticmethod
    def _action_requests(interrupt: Any) -> tuple[Mapping[str, Any], ...]:
        """Read the actions carried by one interrupt, tolerating another shape.

        An interrupt raised by something other than this middleware carries a
        payload of its own. It is not an approval request and is skipped rather
        than guessed at.
        """
        value = getattr(interrupt, "value", None)
        if not isinstance(value, Mapping):
            return ()
        requests = value.get("action_requests")
        if not isinstance(requests, Sequence) or isinstance(requests, str | bytes):
            return ()
        return tuple(request for request in requests if isinstance(request, Mapping))

    def resume_command(self, decisions: Sequence[Mapping[str, Any]]) -> Command[Any]:
        """Build the command that resumes the suspended calls.

        The framework matches decisions to actions by position, so the order the
        approvals were read in is the order they must be answered in.
        """
        _logger.debug("Building LangGraph resume command with %d decisions", len(decisions))
        return Command(resume={"decisions": list(decisions)})

    def decision_for(
        self,
        request: ConfirmationRequest,
        user: UserContext,
        *,
        approved: bool,
    ) -> ConfirmationDecision:
        """Build the domain decision matching a confirmation request."""
        _logger.debug(
            "Creating ConfirmationDecision (request_id=%s, approved=%s, decided_by=%s)",
            request.request_id,
            approved,
            user.user_id,
        )
        return ConfirmationDecision(
            request_id=request.request_id,
            approved=approved,
            decided_by=user.user_id,
        )
