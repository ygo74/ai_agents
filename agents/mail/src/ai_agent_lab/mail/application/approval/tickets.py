"""Answering approvals when nobody is waiting at a console.

An OpenAI-compatible API answers every request, so a turn cannot hold while a
person decides. The turn therefore ends having changed nothing: each suspended
call is declined *to the framework* and kept as a ticket, and the reply says what
is waiting.

What happens once the person answers is not specific to this agent or to
Microsoft Agent Framework, and lives in
:mod:`ygo74.agent_runtime.domains.humanapproval.confirmed_operations`. What is specific - and all that
remains here - is reading the calls *this* framework suspended and answering
them in the shape it expects.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ygo74.agent_runtime.domains.humanapproval.confirmed_operations import ConfirmationPresenter
from ygo74.agent_runtime.domains.humanapproval.tickets import (
    ConfirmationTicket,
    PendingConfirmationStore,
)
from ygo74.agent_runtime.domains.security.security_errors import SecurityError
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.maf.approval import PendingToolApproval
from ai_agent_lab.mail.application.approval.resolver import ApprovalRound

_logger = logging.getLogger(__name__)


class TicketApprovalResolver:
    """Turns suspended calls into tickets and lets the turn end."""

    def __init__(
        self,
        presenter: ConfirmationPresenter,
        store: PendingConfirmationStore,
        user: UserContext,
        *,
        conversation_id: str,
    ) -> None:
        _logger.info("Initializing Mail Agent ticket approval resolver")
        _logger.debug(
            "TicketApprovalResolver.__init__ arguments: presenter_type=%s, store_type=%s, "
            "user_id=%s, conversation_id=%s",
            type(presenter).__name__,
            type(store).__name__,
            user.user_id,
            conversation_id,
        )
        self._presenter = presenter
        self._store = store
        self._user = user
        self._conversation_id = conversation_id

    def will_question(self, pending: Sequence[PendingToolApproval]) -> bool:
        """Never: this surface has nobody to interrupt.

        The session's question budget therefore does not apply, which is right -
        it guards a person's attention, and no attention is being spent here.
        """
        _logger.info("Checking whether deferred Mail approvals question the user")
        _logger.debug(
            "TicketApprovalResolver.will_question arguments: pending=%d, tool_names=%s",
            len(pending),
            tuple(approval.tool_name for approval in pending),
        )
        return False

    async def resolve(self, pending: Sequence[PendingToolApproval]) -> ApprovalRound:
        """Record a ticket per call, and decline all of them for now.

        Declining is what makes this safe. The framework will not run a batch
        until every call in it is answered, and an operation that is merely
        *described* must not execute, so the honest answer to "may this run?" at
        this point is no.
        """
        _logger.info("Resolving deferred Mail approval batch")
        _logger.debug(
            "TicketApprovalResolver.resolve arguments: pending=%d, tool_names=%s, user_id=%s, conversation_id=%s",
            len(pending),
            tuple(approval.tool_name for approval in pending),
            self._user.user_id,
            self._conversation_id,
        )
        _logger.info("Creating tickets for pending Mail approval loop")
        answers = []
        for approval in pending:
            await self._raise_ticket(approval)
            answers.append(approval.answer(approved=False))
        return ApprovalRound(answers=tuple(answers), questioned_user=False)

    async def _raise_ticket(self, approval: PendingToolApproval) -> None:
        """Describe one call and keep it, arguments included.

        A capability that cannot be described raises no ticket: offering to
        confirm something nobody can read would be a formality, and the call has
        already been declined either way.
        """
        _logger.debug(
            "TicketApprovalResolver._raise_ticket arguments: tool_name=%s, "
            "argument_names=%s, user_id=%s, conversation_id=%s",
            approval.tool_name,
            tuple(sorted(approval.arguments)),
            self._user.user_id,
            self._conversation_id,
        )
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
