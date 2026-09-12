"""Resolution of suspended tool calls at a console.

The framework decides *that* a call must be approved; this decides *who answers
and how*.

Answering has two halves, and only one of them is the question. The framework
needs an ``approve`` or ``reject`` to resume the graph. The domain needs the very
request the user read, together with their answer, recorded in the confirmation
ledger - otherwise the gated skill reaches
:class:`~ai_agent_lab.core.security.unattended.UnattendedApprovalAuthority`, which
refuses, and an approved write fails as though nobody had approved it.

Recording both halves in one place is what keeps them from drifting apart.
"""

from __future__ import annotations

from typing import Any

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationLedger,
    ConfirmationOutcome,
    ConfirmationRequest,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.langgraph.approval import PendingToolApproval
from ai_agent_lab.wiki.application.confirmation_presenter import WikiConfirmationPresenter


class Console:
    """Reads from and writes to the terminal."""

    _EXITS = frozenset({"exit", "quit", "q"})

    def write(self, text: str = "") -> None:
        """Print a line, degrading characters the terminal cannot render."""
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"))

    def prompt(self, label: str) -> str:
        """Read one line from the user."""
        return input(label)

    def is_exit(self, message: str) -> bool:
        """Whether the user asked to leave."""
        return message.strip().casefold() in self._EXITS


class ConsoleApprovalResolver:
    """Asks the person at the console whether a gated operation may run."""

    def __init__(
        self,
        console: Console,
        presenter: WikiConfirmationPresenter,
        ledger: ConfirmationLedger,
        user: UserContext,
    ) -> None:
        self._console = console
        self._presenter = presenter
        self._ledger = ledger
        self._user = user

    def will_question(self, pending: tuple[PendingToolApproval, ...]) -> bool:
        """Every suspended call is put to the user."""
        return bool(pending)

    async def resolve(self, pending: tuple[PendingToolApproval, ...]) -> list[dict[str, Any]]:
        """Ask about each suspended call, in the order the middleware gave.

        Order matters: the framework matches decisions to actions by position,
        and answering them out of order would approve one operation with the
        answer given for another.
        """
        return [await self._decide(approval) for approval in pending]

    async def _decide(self, approval: PendingToolApproval) -> dict[str, Any]:
        """Put one operation to the user, record the answer and resume.

        A capability that cannot be described is declined rather than approved
        blindly. An unreadable prompt is not a safeguard, and asking somebody to
        approve an operation nobody can explain is worse than interrupting them.
        """
        try:
            request = await self._presenter.present(approval.tool_name, approval.arguments, self._user)
        except DomainError as error:
            self._console.write(f"\n[confirmation] cannot describe {approval.tool_name}: {error}")
            self._console.write("  -> declined")
            return approval.answer(approved=False)

        approved = self._ask(request)
        self._record(request, approved=approved)
        return approval.answer(approved=approved)

    def _ask(self, request: ConfirmationRequest) -> bool:
        """Show what would happen and read the answer.

        Anything that is not an explicit yes is a refusal. A person who presses
        return without reading, or who is not there at all, must not thereby
        authorise a change to a wiki their colleagues rely on.
        """
        operation = request.operation
        self._console.write(f"\n{request.title}")
        self._console.write(f"  Operation: {operation.tool_name} (risk: {operation.risk_level.value})")
        for detail in request.details:
            self._console.write(f"  {detail.label}: {detail.value}")
        answer = self._console.prompt("Allow it? [y/N] ").strip().casefold()
        return answer in {"y", "yes"}

    def _record(self, request: ConfirmationRequest, *, approved: bool) -> None:
        """Store the answer so the gated skill enforces this very decision."""
        decision = ConfirmationDecision(
            request_id=request.request_id,
            approved=approved,
            decided_by=self._user.user_id,
        )
        self._ledger.record(ConfirmationOutcome(request=request, decision=decision), self._user)
