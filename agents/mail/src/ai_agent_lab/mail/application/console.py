"""Console interaction: turns, approvals and rendering."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from ai_agent_lab.core.security.confirmation import ConfirmationRequest

_AFFIRMATIVE = frozenset({"y", "yes", "o", "oui"})
_NEGATIVE = frozenset({"n", "no", "non"})
_ALL = frozenset({"a", "all", "t", "tout", "toujours"})
_EXIT = frozenset({"exit", "quit", ":q"})


class ConfirmationAnswer(StrEnum):
    """What the user replied to one confirmation.

    ``APPROVE_ALL`` is separate from ``APPROVE`` because it is a decision about
    future operations as well as this one, and only the caller knows whether
    that is allowed for this capability.
    """

    APPROVE = "approve"
    DECLINE = "decline"
    APPROVE_ALL = "approve_all"


class Console:
    """Reads from and writes to the terminal.

    Isolating the input and output behind one small class keeps the session
    loop testable without patching builtins.

    It also absorbs what a terminal cannot render. Confirmation prompts quote
    real mail subjects, and a subject is written by a stranger: emoji and
    scripts a legacy Windows code page has no byte for arrive routinely. Left
    alone, printing one raises ``UnicodeEncodeError`` in the middle of an
    approval, aborting a turn with outstanding decisions. A character nobody can
    display is a display problem, never a reason to abandon a turn.
    """

    def __init__(
        self,
        reader: Callable[[str], str] = input,
        writer: Callable[[str], None] = print,
    ) -> None:
        self._reader = reader
        self._writer = writer

    def write(self, text: str = "") -> None:
        """Write one line, degrading characters the terminal cannot encode."""
        try:
            self._writer(text)
        except UnicodeEncodeError:
            self._writer(_displayable(text))

    def prompt(self, label: str) -> str:
        """Read one line from the user."""
        try:
            return self._reader(label)
        except UnicodeEncodeError:
            return self._reader(_displayable(label))

    @staticmethod
    def is_exit(text: str) -> bool:
        """Whether the user asked to leave."""
        return text.strip().casefold() in _EXIT


def _displayable(text: str) -> str:
    """Return the text with unencodable characters replaced.

    ASCII is the one encoding every terminal agrees on. Falling back to it
    loses accents that would have rendered, which is a fair price for never
    losing the line itself.
    """
    return text.encode("ascii", errors="replace").decode("ascii")


class ConsoleConfirmationPrompt:
    """Asks the user to approve a state-changing operation.

    The answer must be explicit. Anything that is not a clear yes is treated as
    a refusal, so an ambiguous keystroke can never send an email.
    """

    def __init__(self, console: Console) -> None:
        self._console = console

    def ask(self, request: ConfirmationRequest, *, offer_all: bool = False) -> ConfirmationAnswer:
        """Show the request and return the user's answer.

        Args:
            request: What the user is being asked to approve.
            offer_all: Whether "approve every one of these" may be offered. It
                is refused for operations no configuration may weaken, so the
                interface never proposes a choice the policy would ignore.
        """
        self._console.write()
        self._console.write(f"[confirmation] {request.title}")
        self._console.write(f"  operation: {request.operation.tool_name} ({request.operation.risk_level.value} risk)")
        self._console.write(f"  reference: {request.request_id}")
        for detail in request.details:
            self._console.write(f"  {detail.label}: {self._indent(detail.value)}")
        answer = self._read(offer_all=offer_all)
        self._console.write(f"  -> {_REPORTED[answer]}")
        return answer

    def _read(self, *, offer_all: bool) -> ConfirmationAnswer:
        """Read one answer, defaulting to a refusal."""
        hint = "  approve? [y/N/a=all of this kind] " if offer_all else "  approve? [y/N] "
        answer = self._console.prompt(hint).strip().casefold()
        if offer_all and answer in _ALL:
            return ConfirmationAnswer.APPROVE_ALL
        if answer in _AFFIRMATIVE:
            return ConfirmationAnswer.APPROVE
        return ConfirmationAnswer.DECLINE

    @staticmethod
    def _indent(value: str) -> str:
        """Keep multi-line details readable."""
        return value.replace("\n", "\n    ")


_REPORTED = {
    ConfirmationAnswer.APPROVE: "approved",
    ConfirmationAnswer.DECLINE: "declined",
    ConfirmationAnswer.APPROVE_ALL: "approved, and every further one of these in this conversation",
}
