"""Tests of the console, where mail from strangers reaches a terminal.

A confirmation prompt quotes real subjects and real sender names. Those are
written by whoever sent the message: emoji, scripts a legacy Windows code page
has no byte for, and control characters all arrive routinely.

None of that may end a turn. A turn dies with approvals still outstanding, and
the framework keeps them in the session, so a crash in the middle of a prompt is
considerably worse than a mangled character.
"""

from __future__ import annotations

import pytest

from ai_agent_lab.core.security.confirmation import ConfirmationDetail, ConfirmationRequest
from ai_agent_lab.core.security.operations import OperationType, RiskLevel, ToolOperationDescriptor
from ai_agent_lab.mail.application.console import (
    ConfirmationAnswer,
    Console,
    ConsoleConfirmationPrompt,
)
from ai_agent_lab.mail.domain.permissions import MailPermission

EMOJI_SUBJECT = "\U0001f600 Sale now on \u2013 50% off"

APPLY_LABEL = ToolOperationDescriptor(
    tool_name="apply_label",
    operation_type=OperationType.WRITE,
    risk_level=RiskLevel.MEDIUM,
    required_permission=MailPermission.MANAGE,
    confirmation_required_by_default=True,
)


class LegacyTerminal:
    """A writer that refuses anything a Windows code page cannot encode."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        """Accept a line only if cp1252 could carry it."""
        text.encode("cp1252")
        self.lines.append(text)

    def read(self, label: str) -> str:
        """Echo the prompt back, refusing what cp1252 cannot carry."""
        label.encode("cp1252")
        return "y"


class TestAnUnrenderableCharacterNeverEndsATurn:
    """The prompt degrades the character, never the line."""

    def test_a_subject_the_terminal_cannot_encode_is_still_written(self):
        terminal = LegacyTerminal()
        console = Console(reader=terminal.read, writer=terminal.write)

        console.write(f"Subject: {EMOJI_SUBJECT}")

        assert terminal.lines
        assert "Sale now on" in terminal.lines[0]

    def test_the_whole_confirmation_survives_an_emoji_subject(self):
        terminal = LegacyTerminal()
        console = Console(reader=terminal.read, writer=terminal.write)
        prompt = ConsoleConfirmationPrompt(console)

        answer = prompt.ask(_request_showing(EMOJI_SUBJECT))

        assert answer is ConfirmationAnswer.APPROVE
        assert any("Sale now on" in line for line in terminal.lines)

    def test_a_terminal_that_copes_sees_the_text_unchanged(self):
        """Degrading is a fallback, not the normal path."""
        written: list[str] = []
        console = Console(writer=written.append)

        console.write(EMOJI_SUBJECT)

        assert written == [EMOJI_SUBJECT]

    def test_reading_survives_an_unencodable_prompt(self):
        terminal = LegacyTerminal()
        console = Console(reader=terminal.read, writer=terminal.write)

        assert console.prompt(f"{EMOJI_SUBJECT} > ") == "y"


class TestTheStandingAnswerIsOnlyOfferedWhenAllowed:
    """A choice the policy would ignore must not be presented."""

    def test_the_hint_appears_only_when_offered(self):
        written: list[str] = []
        answers = iter(["y", "y"])
        console = Console(reader=lambda label: _record(label, written) or next(answers), writer=written.append)
        prompt = ConsoleConfirmationPrompt(console)

        prompt.ask(_request_showing("Anything"), offer_all=True)
        offered = [line for line in written if "all of this kind" in line]

        written.clear()
        prompt.ask(_request_showing("Anything"), offer_all=False)
        withheld = [line for line in written if "all of this kind" in line]

        assert offered
        assert not withheld

    @pytest.mark.security
    def test_answering_all_where_it_is_not_offered_is_a_refusal(self):
        console = Console(reader=lambda _label: "a", writer=lambda _text: None)
        prompt = ConsoleConfirmationPrompt(console)

        assert prompt.ask(_request_showing("Anything"), offer_all=False) is ConfirmationAnswer.DECLINE

    def test_answering_all_where_it_is_offered_stands(self):
        console = Console(reader=lambda _label: "a", writer=lambda _text: None)
        prompt = ConsoleConfirmationPrompt(console)

        assert prompt.ask(_request_showing("Anything"), offer_all=True) is ConfirmationAnswer.APPROVE_ALL

    @pytest.mark.security
    def test_anything_unclear_is_a_refusal(self):
        console = Console(reader=lambda _label: "maybe", writer=lambda _text: None)
        prompt = ConsoleConfirmationPrompt(console)

        assert prompt.ask(_request_showing("Anything"), offer_all=True) is ConfirmationAnswer.DECLINE


def _record(label: str, written: list[str]) -> None:
    """Capture the prompt line itself, which carries the offered answers."""
    written.append(label)


def _request_showing(subject: str) -> ConfirmationRequest:
    """A confirmation quoting a subject written by somebody else."""
    return ConfirmationRequest(
        request_id="cfm-1",
        operation=APPLY_LABEL,
        requested_for="owner",
        title="Apply this label to the message?",
        target="m-1",
        details=(
            ConfirmationDetail(label="Message", value="m-1"),
            ConfirmationDetail(label="Subject", value=subject),
        ),
    )
