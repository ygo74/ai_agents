"""Answering approvals when nobody is waiting at a console.

An OpenAI-compatible API answers every request, so a turn cannot hold while a
person decides. The turn therefore ends having changed nothing: each suspended
call is declined *to the framework* and kept as a ticket, and the reply says what
is waiting.

The answer arrives in a later request as plain text. It is read by a literal
parser before the model sees it, the ticket is claimed, and the capability is
re-invoked from the arguments stored in that ticket. This is the property worth
stating twice: the model describes the operation, then plays no part in running
it. It cannot alter the arguments between the two, because they never come back
through it.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.registry import ResultRenderer, SkillRegistry
from ai_agent_lab.core.security.commands import ConfirmationCommand
from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationLedger,
    ConfirmationOutcome,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.tickets import (
    ConfirmationTicket,
    PendingConfirmationStore,
)
from ai_agent_lab.maf.approval import PendingToolApproval
from ai_agent_lab.mail.application.approval.resolver import ApprovalRound
from ai_agent_lab.mail.application.confirmation_presenter import MailConfirmationPresenter


class TicketApprovalResolver:
    """Turns suspended calls into tickets and lets the turn end."""

    def __init__(
        self,
        presenter: MailConfirmationPresenter,
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

    async def resolve(self, pending: Sequence[PendingToolApproval]) -> ApprovalRound:
        """Record a ticket per call, and decline all of them for now.

        Declining is what makes this safe. The framework will not run a batch
        until every call in it is answered, and an operation that is merely
        *described* must not execute, so the honest answer to "may this run?" at
        this point is no.
        """
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
        try:
            request = await self._presenter.present(approval.tool_name, approval.arguments, self._user)
        except DomainError:
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


class ConfirmedOperationRunner:
    """Runs the operation a claimed ticket describes, and nothing else."""

    def __init__(
        self,
        registry: SkillRegistry,
        store: PendingConfirmationStore,
        ledger: ConfirmationLedger,
        renderer: ResultRenderer,
        user: UserContext,
        *,
        conversation_id: str,
    ) -> None:
        self._registry = registry
        self._store = store
        self._ledger = ledger
        self._renderer = renderer
        self._user = user
        self._conversation_id = conversation_id

    async def run(self, command: ConfirmationCommand) -> str:
        """Claim the ticket the command names, then honour the answer.

        Claiming first is deliberate: a refusal must consume the ticket too, so
        a declined operation cannot be confirmed a moment later by repeating the
        identifier.
        """
        ticket = self._store.claim(
            command.ticket_id,
            subject=self._user.user_id,
            conversation_id=self._conversation_id,
        )
        if not command.approves:
            return f"Cancelled {ticket.tool_name}. Nothing was changed."

        self._record(ticket)
        descriptor = self._registry.skill(ticket.tool_name)
        payload = descriptor.input_model.model_validate(dict(ticket.arguments))
        return self._renderer.render(await descriptor.invoke(payload, self._user))

    def _record(self, ticket: ConfirmationTicket) -> None:
        """Store the decision so the domain gate enforces this very request."""
        self._ledger.record(
            ConfirmationOutcome(
                request=ticket.request,
                decision=ConfirmationDecision(
                    request_id=ticket.request.request_id,
                    approved=True,
                    decided_by=self._user.user_id,
                ),
            ),
            self._user,
        )
