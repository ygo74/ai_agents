"""Translation between framework approvals and domain confirmations.

Microsoft Agent Framework suspends a tool call registered with
``approval_mode="always_require"`` and reports it through
``AgentResponse.user_input_requests``. The host answers with a
``function_approval_response`` content.

This module converts those framework contents into the vocabulary the
application already uses, so the console, a future chat surface and the domain
gate all speak about the same thing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agent_framework import AgentResponse, Content, Message
from ygo74.agent_runtime.domains.humanapproval.confirmation import (
    ConfirmationDecision,
    ConfirmationRequest,
)
from ygo74.agent_runtime.domains.security.user_context import UserContext

APPROVAL_REQUEST_TYPE = "function_approval_request"


class PendingToolApproval:
    """One suspended tool call waiting for the user's answer."""

    def __init__(self, content: Content) -> None:
        self._content = content

    @property
    def content(self) -> Content:
        """The framework content this approval refers to."""
        return self._content

    @property
    def tool_name(self) -> str:
        """Name of the capability the model wants to run."""
        call = getattr(self._content, "function_call", None)
        return "" if call is None else str(getattr(call, "name", ""))

    @property
    def arguments(self) -> Mapping[str, Any]:
        """Arguments the model proposed, always a mapping."""
        call = getattr(self._content, "function_call", None)
        raw = None if call is None else getattr(call, "arguments", None)
        if isinstance(raw, Mapping):
            return dict(raw)
        if isinstance(raw, str) and raw.strip():
            return _parse_arguments(raw)
        return {}

    def answer(self, *, approved: bool) -> Content:
        """Build the framework content carrying the user's answer."""
        return self._content.to_function_approval_response(approved=approved)


def _parse_arguments(raw: str) -> Mapping[str, Any]:
    """Decode JSON arguments, tolerating a malformed payload."""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


class MafApprovalTranslator:
    """Reads pending approvals and builds the messages that answer them."""

    def pending_approvals(self, response: AgentResponse[Any]) -> tuple[PendingToolApproval, ...]:
        """Every tool call the framework suspended in this response."""
        return tuple(
            PendingToolApproval(content)
            for content in response.user_input_requests
            if content.type == APPROVAL_REQUEST_TYPE
        )

    def answer_message(self, answers: Sequence[Content]) -> Message:
        """Build the user message that resumes the suspended calls."""
        return Message(role="user", contents=list(answers))

    def decision_for(
        self,
        request: ConfirmationRequest,
        user: UserContext,
        *,
        approved: bool,
    ) -> ConfirmationDecision:
        """Build the domain decision matching a confirmation request."""
        return ConfirmationDecision(
            request_id=request.request_id,
            approved=approved,
            decided_by=user.user_id,
        )
