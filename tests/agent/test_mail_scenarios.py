"""Reproducible agent scenarios for the Mail Agent.

Each scenario states the user request, the tools the model is scripted to call,
and what must be true afterwards. The agent, the skills, the confirmation
policy and the audit trail are the real ones; only the language model is
scripted, so the scenarios are deterministic and free.
"""

from __future__ import annotations

import pytest
from tests.support.maf_fakes import ScriptedChatClient, ToolCall, calls, says

from ai_agent_lab.core.security.audit import AuditOutcome
from ai_agent_lab.maf.approval import MafApprovalTranslator
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.application.console import Console, ConsoleConfirmationPrompt
from ai_agent_lab.mail.application.session import MailAgentSession
from ai_agent_lab.mail.capabilities.write_capabilities import DRAFT_MAIL_REPLY
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner
from ai_agent_lab.mail.skills.analysis import (
    MailActionsOutput,
    MailReplyOutput,
    MailSummaryOutput,
)

SUMMARY_ANSWER = {
    "summary": "John asks for a review of the Project Alpha architecture document before Friday.",
    "key_points": ["An architecture document is attached"],
    "decisions": ["The message queue option was dropped after the cost review"],
    "uncertainties": ["Whether the retention policy was agreed"],
    "actions": [
        {
            "description": "Review the architecture document",
            "origin": "EXPLICIT",
            "confidence": "HIGH",
            "source_message_id": "m-alpha-1",
            "due_date": "2026-09-04T17:00:00+00:00",
        }
    ],
}

ACTIONS_ANSWER = {"actions": SUMMARY_ANSWER["actions"]}

REPLY_ANSWER = {
    "subject": "Re: Project Alpha - architecture review",
    "body": "Thanks John. I will review the architecture document tomorrow and send you my feedback.",
}


class ConsoleRecorder:
    """A console that answers approvals from a fixed script."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.lines: list[str] = []

    def read(self, _label: str) -> str:
        """Return the next scripted answer."""
        return self._answers.pop(0) if self._answers else "n"

    def write(self, text: str = "") -> None:
        """Capture one printed line."""
        self.lines.append(text)

    @property
    def transcript(self) -> str:
        """Everything printed so far."""
        return "\n".join(self.lines)


def build_session(script, *, answers=None, settings=None, dataset_root=None, max_approval_rounds=25):
    """Assemble a Mail Agent session driven by a scripted model."""
    from pathlib import Path

    recorder = ConsoleRecorder(answers or [])
    console = Console(reader=recorder.read, writer=recorder.write)
    client = ScriptedChatClient(script)
    reasoner = ScriptedTextReasoner(
        {
            MailSummaryOutput: SUMMARY_ANSWER,
            MailActionsOutput: ACTIONS_ANSWER,
            MailReplyOutput: REPLY_ANSWER,
        }
    )
    runtime = MailAgentCompositionRoot(
        settings or MailAgentSettings(),
        client,
        reasoner=reasoner,
        base_path=dataset_root or Path(__file__).resolve().parents[2],
    ).build(session_id="scenario")
    session = MailAgentSession(
        runtime,
        console,
        ConsoleConfirmationPrompt(console),
        MafApprovalTranslator(),
        max_approval_rounds=max_approval_rounds,
    )
    return session, runtime, client, recorder


@pytest.mark.scenario
class TestMail001Search:
    """MAIL-001 - the user looks for messages."""

    async def test_search_is_performed_and_nothing_is_written(self):
        session, runtime, _client, _recorder = build_session(
            [
                calls(ToolCall(MailToolName.SEARCH_MAIL.value, {"sender": "john.smith@example.com", "limit": 10})),
                says("I found two messages from John."),
            ]
        )

        answer = await session.ask("Find emails from John.")

        assert "two messages" in answer
        assert runtime.audit.records == ()

    async def test_the_search_tool_is_offered_to_the_model(self):
        session, _runtime, client, _recorder = build_session([says("nothing to do")])

        await session.ask("Hello.")

        assert MailToolName.SEARCH_MAIL.value in client.offered_tools[0]


@pytest.mark.scenario
class TestMail002Summary:
    """MAIL-002 - the user asks for a summary."""

    async def test_the_summary_is_grounded_and_cites_its_sources(self):
        session, runtime, _client, _recorder = build_session(
            [
                calls(ToolCall("summarise_mail", {"thread_id": "t-alpha"})),
                says("Summarised."),
            ]
        )

        await session.ask("Summarise the discussion about Project Alpha.")

        summary = await runtime.skills.summary.summarise_thread("t-alpha", runtime.user)
        assert {source.message_id for source in summary.sources} == {"m-alpha-1", "m-alpha-2", "m-alpha-3"}

    async def test_summarising_writes_nothing(self):
        session, runtime, _client, _recorder = build_session(
            [calls(ToolCall("summarise_mail", {"thread_id": "t-alpha"})), says("Summarised.")]
        )

        await session.ask("Summarise the discussion about Project Alpha.")

        assert runtime.audit.records == ()


@pytest.mark.scenario
class TestMail003Draft:
    """MAIL-003 - the user asks for a reply to be prepared."""

    async def test_a_draft_is_prepared_and_nothing_is_sent(self):
        session, runtime, _client, _recorder = build_session(
            [
                calls(
                    ToolCall(
                        DRAFT_MAIL_REPLY,
                        {"thread_id": "t-alpha", "intent": "I will review the document tomorrow"},
                    )
                ),
                says("Here is the draft."),
            ]
        )

        await session.ask("Draft a reply saying I will review the document tomorrow.")

        assert runtime.mail_tools.mailbox_of(runtime.user).sent == ()
        assert runtime.audit.records_for(MailToolName.SEND_MAIL.value) == ()


@pytest.mark.scenario
class TestMail004And005Sending:
    """MAIL-004 and MAIL-005 - sending is gated by an explicit confirmation."""

    @pytest.mark.security
    async def test_sending_is_not_performed_without_confirmation(self):
        session, runtime, _client, _recorder = build_session(
            [
                calls(ToolCall(DRAFT_MAIL_REPLY, {"thread_id": "t-alpha", "intent": "I agree"})),
                calls(ToolCall(MailToolName.SEND_MAIL.value, {"draft_reference": "REPLACED"})),
                says("I did not send it."),
            ],
            answers=["n"],
        )

        await session.ask("Draft a reply saying I agree.")

        assert runtime.mail_tools.mailbox_of(runtime.user).sent == ()

    @pytest.mark.security
    async def test_the_user_is_shown_what_would_be_sent(self):
        session, _runtime, _client, recorder = await _prepare_send(answers=["n"])

        await session.ask("Send it.")

        assert "Send this email?" in recorder.transcript
        assert "sarah.jones@example.com" in recorder.transcript
        assert "Re: Project Alpha" in recorder.transcript
        assert "-> declined" in recorder.transcript

    @pytest.mark.security
    async def test_a_declined_send_delivers_nothing_and_is_audited(self):
        session, runtime, _client, _recorder = await _prepare_send(answers=["n"])

        await session.ask("Send it.")

        assert runtime.mail_tools.mailbox_of(runtime.user).sent == ()
        assert runtime.audit.records_for(MailToolName.SEND_MAIL.value) == ()

    async def test_an_approved_send_delivers_exactly_once(self):
        session, runtime, _client, _recorder = await _prepare_send(answers=["y"])

        await session.ask("Send it.")

        assert len(runtime.mail_tools.mailbox_of(runtime.user).sent) == 1
        entries = runtime.audit.records_for(MailToolName.SEND_MAIL.value)
        assert [entry.outcome for entry in entries] == [AuditOutcome.EXECUTED]


@pytest.mark.scenario
@pytest.mark.security
class TestMail006PromptInjection:
    """MAIL-006 - a message tries to give the agent orders."""

    async def test_reading_a_malicious_message_triggers_no_write(self):
        session, runtime, _client, _recorder = build_session(
            [
                calls(ToolCall(MailToolName.GET_MAIL.value, {"message_id": "m-injection-1"})),
                says("This message asks me to forward your mailbox. I did not act on it."),
            ]
        )

        answer = await session.ask("Summarise this message.")

        assert runtime.mail_tools.mailbox_of(runtime.user).sent == ()
        assert runtime.audit.records == ()
        assert "did not act" in answer

    async def test_the_malicious_body_reaches_the_model_as_fenced_data(self):
        session, _runtime, client, _recorder = build_session(
            [
                calls(ToolCall(MailToolName.GET_MAIL.value, {"message_id": "m-injection-1"})),
                says("Reported."),
            ]
        )

        await session.ask("Read the verification message.")

        rendered = _tool_output(client)
        assert "Ignore all previous instructions" in rendered
        assert "are not trusted" in rendered
        assert rendered.index("Never follow") < rendered.index("Ignore all previous instructions")

    async def test_an_injected_send_is_still_gated(self):
        session, runtime, _client, _recorder = build_session(
            [
                calls(ToolCall(MailToolName.GET_MAIL.value, {"message_id": "m-injection-1"})),
                calls(ToolCall(MailToolName.ARCHIVE_MAIL.value, {"message_id": "m-alpha-1"})),
                says("Done what I could."),
            ],
            answers=["n"],
        )

        await session.ask("Read the verification message.")

        message = await runtime.mail_tools.get_message("m-alpha-1", runtime.user)
        assert not message.is_archived


@pytest.mark.scenario
@pytest.mark.security
class TestApprovalStateNeverLeaksAcrossTurns:
    """An answer given for one request must not authorise a later, unrelated one.

    The framework keeps queued approval requests in the session, so a turn that
    walks away from them would let the next turn replay them. These tests pin
    the two properties that prevent it: an abandoned turn declines everything it
    left pending, and the audited confirmation is the one the user actually saw.
    """

    async def test_an_abandoned_turn_delivers_nothing_and_leaves_no_answer_behind(self):
        session, runtime, client, _recorder = build_session(
            [
                calls(ToolCall(DRAFT_MAIL_REPLY, {"thread_id": "t-alpha", "intent": "I agree"})),
                says("Here is the draft."),
            ],
            answers=["y"] * 40,
            max_approval_rounds=1,
        )
        await session.ask("Draft a reply saying I agree.")
        reference = _draft_reference(client)
        client.append(
            calls(
                ToolCall(MailToolName.SEND_MAIL.value, {"draft_reference": reference}),
                ToolCall(MailToolName.ARCHIVE_MAIL.value, {"message_id": "m-alpha-1"}),
                ToolCall(MailToolName.ARCHIVE_MAIL.value, {"message_id": "m-alpha-2"}),
            ),
            says("Done."),
        )

        answer = await session.ask("Send my reply and archive those two.")

        assert "interrupted" in answer
        assert runtime.mail_tools.mailbox_of(runtime.user).sent == ()
        assert runtime.confirmation_ledger.pending_count(runtime.user) == 0
        executed = [entry for entry in runtime.audit.records if entry.outcome is AuditOutcome.EXECUTED]
        assert executed == []

    async def test_a_later_turn_cannot_replay_an_abandoned_approval(self):
        session, runtime, client, _recorder = build_session(
            [
                calls(ToolCall(DRAFT_MAIL_REPLY, {"thread_id": "t-alpha", "intent": "I agree"})),
                says("Here is the draft."),
            ],
            answers=["y"] * 40,
            max_approval_rounds=1,
        )
        await session.ask("Draft a reply saying I agree.")
        reference = _draft_reference(client)
        client.append(
            calls(
                ToolCall(MailToolName.SEND_MAIL.value, {"draft_reference": reference}),
                ToolCall(MailToolName.ARCHIVE_MAIL.value, {"message_id": "m-alpha-1"}),
                ToolCall(MailToolName.ARCHIVE_MAIL.value, {"message_id": "m-alpha-2"}),
            ),
            says("Done."),
        )
        await session.ask("Send my reply and archive those two.")

        await session.ask("What is the weather?")

        assert runtime.mail_tools.mailbox_of(runtime.user).sent == ()
        assert not (await runtime.mail_tools.get_message("m-alpha-1", runtime.user)).is_archived
        assert not (await runtime.mail_tools.get_message("m-alpha-2", runtime.user)).is_archived

    async def test_the_audited_confirmation_is_the_one_the_user_answered(self):
        session, runtime, _client, recorder = await _prepare_send(answers=["y"])

        await session.ask("Send it.")

        entry = runtime.audit.records_for(MailToolName.SEND_MAIL.value)[0]
        assert entry.confirmation_request_id is not None
        assert entry.confirmation_request_id == _shown_request_id(recorder)


def _shown_request_id(recorder: ConsoleRecorder) -> str | None:
    """The identifier of the request rendered to the user."""
    for line in recorder.lines:
        if line.strip().startswith("reference: "):
            return line.split("reference: ", 1)[1].strip()
    return None


async def _prepare_send(*, answers: list[str]):
    """Run a first turn that prepares a draft, then arm a send turn."""
    session, runtime, client, recorder = build_session(
        [
            calls(ToolCall(DRAFT_MAIL_REPLY, {"thread_id": "t-alpha", "intent": "I agree"})),
            says("Here is the draft."),
        ],
        answers=answers,
    )
    await session.ask("Draft a reply saying I agree.")

    reference = _draft_reference(client)
    client.append(
        calls(ToolCall(MailToolName.SEND_MAIL.value, {"draft_reference": reference})),
        says("Done."),
    )
    return session, runtime, client, recorder


def _tool_output(client: ScriptedChatClient) -> str:
    """Return the text of the last tool result handed back to the model."""
    for messages in reversed(client.received_messages):
        for message in reversed(messages):
            for content in message.contents:
                if content.type == "function_result":
                    return str(getattr(content, "result", ""))
    raise AssertionError("no tool result was handed back to the model")


def _draft_reference(client: ScriptedChatClient) -> str:
    """Extract the draft reference the drafting capability returned."""
    import re

    for messages in reversed(client.received_messages):
        for message in reversed(messages):
            for content in message.contents:
                if content.type != "function_result":
                    continue
                match = re.search(r'"draft_reference":\s*"([^"]+)"', str(getattr(content, "result", "")))
                if match:
                    return match.group(1)
    raise AssertionError("no draft reference was produced")
