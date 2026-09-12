"""Console interaction: turns, approvals and rendering."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

from ai_agent_lab.core.security.confirmation import ConfirmationRequest

_AFFIRMATIVE = frozenset({"y", "yes", "o", "oui"})
_NEGATIVE = frozenset({"n", "no", "non"})
_ALL = frozenset({"a", "all", "t", "tout", "toujours"})
_EXIT = frozenset({"exit", "quit", ":q"})
_logger = logging.getLogger(__name__)


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
        _logger.info("Initializing Mail Agent console")
        _logger.debug(
            "Console.__init__ arguments: reader_type=%s, writer_type=%s",
            type(reader).__name__,
            type(writer).__name__,
        )
        self._reader = reader
        self._writer = writer

    def write(self, text: str = "") -> None:
        """Write one line, degrading characters the terminal cannot encode."""
        _logger.debug("Console.write arguments: text_length=%d", len(text))
        try:
            self._writer(text)
        except UnicodeEncodeError:
            self._writer(_displayable(text))

    def prompt(self, label: str) -> str:
        """Read one line from the user."""
        _logger.debug("Console.prompt arguments: label_length=%d", len(label))
        try:
            return self._reader(label)
        except UnicodeEncodeError:
            return self._reader(_displayable(label))

    @staticmethod
    def is_exit(text: str) -> bool:
        """Whether the user asked to leave."""
        _logger.debug("Console.is_exit arguments: text_length=%d", len(text))
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
        _logger.info("Initializing Mail Agent console confirmation prompt")
        _logger.debug(
            "ConsoleConfirmationPrompt.__init__ arguments: console_type=%s",
            type(console).__name__,
        )
        self._console = console

    def ask(self, request: ConfirmationRequest, *, offer_all: bool = False) -> ConfirmationAnswer:
        """Show the request and return the user's answer.

        Args:
            request: What the user is being asked to approve.
            offer_all: Whether "approve every one of these" may be offered. It
                is refused for operations no configuration may weaken, so the
                interface never proposes a choice the policy would ignore.
        """
        _logger.info("Asking for Mail operation confirmation")
        _logger.debug(
            "ConsoleConfirmationPrompt.ask arguments: request_id=%s, tool_name=%s, "
            "risk_level=%s, details=%d, offer_all=%s",
            request.request_id,
            request.operation.tool_name,
            request.operation.risk_level.value,
            len(request.details),
            offer_all,
        )
        self._console.write()
        self._console.write(f"[confirmation] {request.title}")
        self._console.write(f"  operation: {request.operation.tool_name} ({request.operation.risk_level.value} risk)")
        self._console.write(f"  reference: {request.request_id}")
        _logger.info("Rendering Mail confirmation detail loop")
        for detail in request.details:
            self._console.write(f"  {detail.label}: {self._indent(detail.value)}")
        answer = self._read(offer_all=offer_all)
        self._console.write(f"  -> {_REPORTED[answer]}")
        return answer

    def _read(self, *, offer_all: bool) -> ConfirmationAnswer:
        """Read one answer, defaulting to a refusal."""
        _logger.info("Reading Mail confirmation answer")
        _logger.debug("ConsoleConfirmationPrompt._read arguments: offer_all=%s", offer_all)
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
        _logger.debug("ConsoleConfirmationPrompt._indent arguments: value_length=%d", len(value))
        return value.replace("\n", "\n    ")


_REPORTED = {
    ConfirmationAnswer.APPROVE: "approved",
    ConfirmationAnswer.DECLINE: "declined",
    ConfirmationAnswer.APPROVE_ALL: "approved, and every further one of these in this conversation",
}
