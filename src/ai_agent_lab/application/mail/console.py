"""Console interaction: turns, approvals and rendering."""

from __future__ import annotations

from collections.abc import Callable

from ai_agent_lab.domain.security.confirmation import ConfirmationRequest

_AFFIRMATIVE = frozenset({"y", "yes", "o", "oui"})
_NEGATIVE = frozenset({"n", "no", "non"})
_EXIT = frozenset({"exit", "quit", ":q"})


class Console:
    """Reads from and writes to the terminal.

    Isolating the input and output behind one small class keeps the session
    loop testable without patching builtins.
    """

    def __init__(
        self,
        reader: Callable[[str], str] = input,
        writer: Callable[[str], None] = print,
    ) -> None:
        self._reader = reader
        self._writer = writer

    def write(self, text: str = "") -> None:
        """Write one line."""
        self._writer(text)

    def prompt(self, label: str) -> str:
        """Read one line from the user."""
        return self._reader(label)

    @staticmethod
    def is_exit(text: str) -> bool:
        """Whether the user asked to leave."""
        return text.strip().casefold() in _EXIT


class ConsoleConfirmationPrompt:
    """Asks the user to approve a state-changing operation.

    The answer must be explicit. Anything that is not a clear yes is treated as
    a refusal, so an ambiguous keystroke can never send an email.
    """

    def __init__(self, console: Console) -> None:
        self._console = console

    def ask(self, request: ConfirmationRequest) -> bool:
        """Show the request and return the user's answer."""
        self._console.write()
        self._console.write(f"[confirmation] {request.title}")
        self._console.write(f"  operation: {request.operation.tool_name} ({request.operation.risk_level.value} risk)")
        for detail in request.details:
            self._console.write(f"  {detail.label}: {self._indent(detail.value)}")
        answer = self._console.prompt("  approve? [y/N] ").strip().casefold()
        approved = answer in _AFFIRMATIVE
        self._console.write("  -> approved" if approved else "  -> declined")
        return approved

    @staticmethod
    def _indent(value: str) -> str:
        """Keep multi-line details readable."""
        return value.replace("\n", "\n    ")
