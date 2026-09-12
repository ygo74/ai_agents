"""Answering approvals when nobody is waiting at a console.

An OpenAI-compatible API answers every request, so a turn cannot hold while a
person decides. The turn therefore ends having changed nothing: each suspended
call is declined *to LangGraph* and kept as a ticket, and the reply says what is
waiting.

What happens once the person answers is not specific to this agent or to
LangGraph, and lives in :mod:`ai_agent_lab.core.serving.confirmations`. What is
specific - and all that remains here - is reading the calls the middleware
suspended and answering them in the shape it expects: a list of decisions,
matched to the actions by position.

This is the LangGraph counterpart of the Mail Agent's resolver, and it is
deliberately shaped the same way. The two differ only where the frameworks do,
which is the whole point of the comparison.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ygo74.agent_runtime.domains.security.security_errors import SecurityError
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.tickets import (
    ConfirmationTicket,
    PendingConfirmationStore,
)
from ai_agent_lab.core.serving.confirmations import ConfirmationPresenter
from ai_agent_lab.langgraph.approval import PendingToolApproval


class WikiTicketApprovalResolver:
    """Turns suspended calls into tickets and lets the turn end."""

    def __init__(
        self,
        presenter: ConfirmationPresenter,
        store: PendingConfirmationStore,
        user: UserContext,
        *,
        conversation_id: str,
    ) -> None:
        self._presenter = presenter
        self._store = store
        self._user = user
        self._conversation_id = conversation_id

    def will_question(self, pending: Sequence[PendingToolApproval]) -> bool:
        """Never: this surface has nobody to interrupt.

        The session's question budget therefore does not apply, which is right -
        it guards a person's attention, and no attention is being spent here.
        """
        del pending
        return False

    async def resolve(self, pending: Sequence[PendingToolApproval]) -> list[dict[str, Any]]:
        """Record a ticket per call, and decline all of them for now.

        Declining is what makes this safe. The middleware will not resume a
        batch until every call in it is answered, and an operation that is
        merely *described* must not execute, so the honest answer to "may this
        run?" at this point is no.

        Order is preserved because LangGraph matches decisions to actions by
        position: answering out of order would reject one operation with the
        answer meant for another.
        """
        answers = []
        for approval in pending:
            await self._raise_ticket(approval)
            answers.append(approval.answer(approved=False))
        return answers

    async def _raise_ticket(self, approval: PendingToolApproval) -> None:
        """Describe one call and keep it, arguments included.

        A capability that cannot be described raises no ticket: offering to
        confirm something nobody can read would be a formality, and the call has
        already been declined either way.
        """
        try:
            request = await self._presenter.present(approval.tool_name, approval.arguments, self._user)
        except (DomainError, SecurityError):
            return

        self._store.issue(
            ConfirmationTicket.issue(
                subject=self._user.user_id,
                conversation_id=self._conversation_id,
                tool_name=approval.tool_name,
                request=request,
                arguments=approval.arguments,
            )
        )
