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


def build_session(
    script,
    *,
    answers=None,
    settings=None,
    dataset_root=None,
    max_approval_rounds=25,
    max_total_rounds=200,
):
    """Assemble a Mail Agent session driven by a scripted model.

    The confirmation posture is stated here rather than inherited from the
    delivered skill packages. Those are configuration: a deployment, or the
    person running the agent, is meant to tune them. A scenario that silently
    borrowed whatever they happened to be would pass or fail for reasons that
    have nothing to do with the code, and would tell somebody tuning their own
    approvals that they had broken the build.

    A scenario about something else passes its own settings.
    """
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
        settings or gated_settings(),
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
        max_total_rounds=max_total_rounds,
    )
    return session, runtime, client, recorder


def gated_settings(**overrides) -> MailAgentSettings:
    """Settings under which every mailbox change is confirmed.

    ``always_confirm`` wins over both the user preferences and the manifest
    default, so this holds whatever the delivered packages say.
    """
    return MailAgentSettings(
        always_confirm_tools=",".join(
            (
                MailToolName.MARK_READ.value,
                MailToolName.ARCHIVE_MAIL.value,
                MailToolName.APPLY_LABEL.value,
                MailToolName.REMOVE_LABEL.value,
            )
        ),
        **overrides,
    )


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


@pytest.mark.scenario
class TestTheApprovalBudgetCountsQuestions:
    """A budget on questions, not on work.

    The interrogation limit exists so a request cannot ask somebody twenty-five
    times in a row. Once they have answered "all of these", it is asking nobody
    anything, and counting those rounds would make the standing answer worthless:
    the questions stop and the turn is interrupted anyway.
    """

    async def test_a_standing_answer_survives_more_rounds_than_the_question_budget(self):
        session, runtime, _client, recorder = build_session(
            _one_label_per_round(6),
            answers=["a"],
            max_approval_rounds=2,
        )

        answer = await session.ask("File the whole thread.")

        assert "interrupted" not in answer
        assert recorder.transcript.count("[confirmation]") == 1
        assert "PROJECT_ALPHA" in (await runtime.mail_tools.get_message("m-alpha-1", runtime.user)).label_ids

    async def test_repeated_questions_still_interrupt_the_turn(self):
        """Without a standing answer, the interrogation limit still applies.

        What the budget stops is the questioning, not what was already agreed
        to. Rounds answered before the limit executed and stay executed; the
        rest never runs.
        """
        session, runtime, _client, _recorder = build_session(
            _one_archive_per_round(6),
            answers=["y"] * 40,
            max_approval_rounds=2,
        )

        answer = await session.ask("Archive everything.")

        assert "interrupted" in answer
        executed = [
            entry
            for entry in runtime.audit.records_for(MailToolName.ARCHIVE_MAIL.value)
            if entry.outcome is AuditOutcome.EXECUTED
        ]
        assert len(executed) == 2
        assert runtime.confirmation_ledger.pending_count(runtime.user) == 0

    async def test_a_runaway_turn_still_ends(self):
        """The ceiling on rounds of any kind is the backstop."""
        session, runtime, _client, _recorder = build_session(
            _one_label_per_round(30),
            answers=["a"],
            max_approval_rounds=50,
            max_total_rounds=4,
        )

        answer = await session.ask("Loop forever.")

        assert "interrupted" in answer
        assert runtime.confirmation_ledger.pending_count(runtime.user) == 0


def _one_label_per_round(rounds: int) -> list:
    """A model that labels one message per round, then stops."""
    script = [
        calls(
            ToolCall(
                MailToolName.APPLY_LABEL.value,
                {"message_id": f"m-alpha-{(index % 3) + 1}", "label_id": "PROJECT_ALPHA"},
            )
        )
        for index in range(rounds)
    ]
    return [*script, says("Filed.")]


def _one_archive_per_round(rounds: int) -> list:
    """A model that archives one message per round, then stops."""
    script = [
        calls(ToolCall(MailToolName.ARCHIVE_MAIL.value, {"message_id": f"m-alpha-{(index % 3) + 1}"}))
        for index in range(rounds)
    ]
    return [*script, says("Done.")]


def _shown_request_id(recorder: ConsoleRecorder) -> str | None:
    """The identifier of the request rendered to the user."""
    for line in recorder.lines:
        if line.strip().startswith("reference: "):
            return line.split("reference: ", 1)[1].strip()
    return None


@pytest.mark.scenario
class TestAConfirmationIsReadable:
    """A prompt nobody can read is not a safeguard, it is a formality.

    Approving is only meaningful if the person understands what they approve.
    These tests pin that the identifiers the model works with are resolved into
    what the mailbox owner recognises.
    """

    async def test_the_prompt_names_the_message_and_the_label(self):
        session, _runtime, _client, recorder = build_session(
            [
                calls(
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-1", "label_id": "PROJECT_ALPHA"},
                    )
                ),
                says("Done."),
            ],
            answers=["y"],
        )

        await session.ask("File that message under Project Alpha.")

        transcript = recorder.transcript
        assert "Project Alpha - architecture review" in transcript
        assert "john.smith@example.com" in transcript
        assert "Project Alpha (PROJECT_ALPHA)" in transcript

    async def test_the_identifiers_stay_next_to_the_readable_facts(self):
        """The identifier is what gets enforced, so it never disappears."""
        session, _runtime, _client, recorder = build_session(
            [
                calls(
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-1", "label_id": "PROJECT_ALPHA"},
                    )
                ),
                says("Done."),
            ],
            answers=["y"],
        )

        await session.ask("File that message under Project Alpha.")

        assert "m-alpha-1" in recorder.transcript

    async def test_an_unreadable_message_still_produces_a_prompt(self):
        """Failing to resolve must not become a refusal to ask."""
        session, _runtime, _client, recorder = build_session(
            [
                calls(
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "does-not-exist", "label_id": "PROJECT_ALPHA"},
                    )
                ),
                says("Done."),
            ],
            answers=["n"],
        )

        await session.ask("File that message under Project Alpha.")

        assert "[confirmation]" in recorder.transcript
        assert "does-not-exist" in recorder.transcript


@pytest.mark.scenario
class TestAnsweringOnceForAWholeKind:
    """Asked the same question twenty times, a person stops reading it."""

    async def test_one_answer_covers_every_further_call_of_that_kind(self):
        session, runtime, _client, recorder = build_session(
            [
                calls(
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-1", "label_id": "PROJECT_ALPHA"},
                    ),
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-2", "label_id": "PROJECT_ALPHA"},
                    ),
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-3", "label_id": "PROJECT_ALPHA"},
                    ),
                ),
                says("Filed."),
            ],
            # One "all", and nothing after it: a second question would exhaust
            # the script and be answered "n", so the labels prove nothing was
            # asked again.
            answers=["a"],
        )

        await session.ask("File the whole Project Alpha thread.")

        for message_id in ("m-alpha-1", "m-alpha-2", "m-alpha-3"):
            message = await runtime.mail_tools.get_message(message_id, runtime.user)
            assert "PROJECT_ALPHA" in message.label_ids
        assert recorder.transcript.count("[confirmation]") == 1

    async def test_every_operation_is_still_audited_individually(self):
        """A standing answer removes the question, never the trace."""
        session, runtime, _client, _recorder = build_session(
            [
                calls(
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-1", "label_id": "PROJECT_ALPHA"},
                    ),
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-2", "label_id": "PROJECT_ALPHA"},
                    ),
                ),
                says("Filed."),
            ],
            answers=["a"],
        )

        await session.ask("File those two.")

        records = runtime.audit.records_for(MailToolName.APPLY_LABEL.value)
        assert len(records) == 2
        assert all(entry.outcome is AuditOutcome.EXECUTED for entry in records)
        assert all(entry.confirmation_request_id is not None for entry in records)

    @pytest.mark.security
    async def test_sending_is_never_offered_a_standing_answer(self):
        """The floor protects sending, so the choice is not even presented."""
        session, _runtime, _client, recorder = await _prepare_send(answers=["y"])

        await session.ask("Send it.")

        assert "all of this kind" not in recorder.transcript

    @pytest.mark.security
    async def test_answering_all_where_it_is_not_offered_declines(self):
        """An answer the interface never offered must not be honoured."""
        session, runtime, _client, _recorder = await _prepare_send(answers=["a"])

        await session.ask("Send it.")

        assert runtime.mail_tools.mailbox_of(runtime.user).sent == ()

    async def test_a_standing_answer_covers_only_the_kind_it_was_given_for(self):
        session, runtime, _client, recorder = build_session(
            [
                calls(
                    ToolCall(
                        MailToolName.APPLY_LABEL.value,
                        {"message_id": "m-alpha-1", "label_id": "PROJECT_ALPHA"},
                    ),
                    ToolCall(MailToolName.ARCHIVE_MAIL.value, {"message_id": "m-alpha-1"}),
                ),
                says("Done."),
            ],
            answers=["a", "n"],
        )

        await session.ask("Label it and archive it.")

        message = await runtime.mail_tools.get_message("m-alpha-1", runtime.user)
        assert "PROJECT_ALPHA" in message.label_ids
        assert not message.is_archived
        assert recorder.transcript.count("[confirmation]") == 2


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
