"""Resolution of suspended tool calls at a console.

Read-only capabilities are never suspended, so in this increment this resolver
approves nothing by construction: there is nothing to approve. It exists now, and
is wired now, because the write capabilities are one delivered manifest away, and
a confirmation path added at the same time as the operations it guards is a
confirmation path nobody reviews.
"""

from __future__ import annotations

from typing import Any

from ai_agent_lab.langgraph.approval import PendingToolApproval


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

    def __init__(self, console: Console) -> None:
        self._console = console

    def will_question(self, pending: tuple[PendingToolApproval, ...]) -> bool:
        """Every suspended call is put to the user."""
        return bool(pending)

    async def resolve(self, pending: tuple[PendingToolApproval, ...]) -> list[dict[str, Any]]:
        """Ask about each suspended call, in the order the middleware gave.

        Order matters: the framework matches decisions to actions by position,
        and answering them out of order would approve one operation with the
        answer given for another.
        """
        return [self._ask(approval) for approval in pending]

    def _ask(self, approval: PendingToolApproval) -> dict[str, Any]:
        """Put one operation to the user and read the answer.

        Anything that is not an explicit yes is a refusal. A person who presses
        return without reading, or who is not there at all, must not thereby
        authorise a change to a wiki their colleagues rely on.
        """
        self._console.write(f"\nThe agent wants to run: {approval.tool_name}")
        for name, value in approval.arguments.items():
            self._console.write(f"  {name}: {value}")
        answer = self._console.prompt("Allow it? [y/N] ").strip().casefold()
        return approval.answer(approved=answer in {"y", "yes"})
