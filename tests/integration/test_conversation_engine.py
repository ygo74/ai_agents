"""Tests of the Mail Agent answering requests instead of a console.

An HTTP surface asks one thing of the agent: given an authenticated caller, a
conversation identifier and a message, return an answer. These tests drive that
port directly - no web framework involved - because what matters here is the
behaviour, not the transport.

Two properties carry the most weight. A confirmation is recognised before the
model is given the turn, so an approval can never be something a model
reinterprets. And a conversation survives between requests, because otherwise
every message would start a new one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.maf_fakes import ScriptedChatClient, ToolCall, calls, says
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.contracts.conversation import ConversationTurn
from ygo74.agent_runtime.domains.sessions.conversation_cache import ConversationRuntimeCache

from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.application.entrypoints.conversation import (
    MailConversation,
    MailConversationEngine,
    MailConversationFactory,
)
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

ADA = AgentPrincipal(subject="local-user", email="local-user@example.com", display_name="Ada")
BOB = AgentPrincipal(subject="other-user", email="other-user@example.com", display_name="Bob")

MESSAGE_ID = "m-alpha-1"
LABEL_ID = "FINANCE"


def gated_settings() -> MailAgentSettings:
    """Settings under which labelling is confirmed, whatever ships in `config/`."""
    return MailAgentSettings(always_confirm_tools=MailToolName.APPLY_LABEL.value)


def build_engine(script) -> tuple[MailConversationEngine, ScriptedChatClient, ConversationRuntimeCache]:
    """Assemble the engine over a scripted model and the deterministic dataset."""
    client = ScriptedChatClient(script)
    factory = MailConversationFactory(
        MailAgentCompositionRoot(
            gated_settings(),
            client,
            reasoner=ScriptedTextReasoner({}),
            base_path=REPOSITORY_ROOT,
        )
    )
    cache: ConversationRuntimeCache[MailConversation] = ConversationRuntimeCache(
        factory.build, MailConversationFactory.close
    )
    return MailConversationEngine(cache), client, cache


def turn(message: str, *, principal: AgentPrincipal = ADA, conversation: str = "conv-1") -> ConversationTurn:
    """Build one request."""
    return ConversationTurn(principal=principal, conversation_id=conversation, message=message)


def labelling_script():
    """A model that asks to file one message, then reports."""
    return [
        calls(ToolCall(MailToolName.APPLY_LABEL.value, {"message_id": MESSAGE_ID, "label_id": LABEL_ID})),
        says("I have asked for confirmation."),
    ]


async def labels_of(cache, message_id: str, principal: AgentPrincipal = ADA) -> tuple[str, ...]:
    """Read the mailbox back through the same conversation."""
    async with cache.lease(principal, "conv-1") as conversation:
        message = await conversation.runtime.mail_tools.get_message(message_id, conversation.runtime.user)
        return message.label_ids


class TestAnOrdinaryTurn:
    """A question is answered and nothing is silently changed."""

    async def test_it_returns_what_the_model_said(self):
        engine, _client, _cache = build_engine([says("I found two messages from John.")])

        reply = await engine.respond(turn("anything from John?"))

        assert "two messages from John" in reply.text

    async def test_nothing_is_pending_when_nothing_was_gated(self):
        engine, _client, _cache = build_engine([says("Nothing to do.")])

        reply = await engine.respond(turn("hello"))

        assert reply.pending_confirmations == ()
        assert not reply.awaits_confirmation


@pytest.mark.security
class TestAGatedOperationDefersInsteadOfBlocking:
    """A request must be answered, so an approval cannot hold the turn."""

    async def test_the_turn_returns_and_changes_nothing(self):
        engine, _client, cache = build_engine(labelling_script())

        reply = await engine.respond(turn("file the Project Alpha message under Finance"))

        assert reply.awaits_confirmation
        assert LABEL_ID not in await labels_of(cache, MESSAGE_ID)

    async def test_the_answer_names_what_is_waiting(self):
        """A ticket nobody can quote is a ticket nobody can answer."""
        engine, _client, _cache = build_engine(labelling_script())

        reply = await engine.respond(turn("file the Project Alpha message under Finance"))

        assert "CONFIRM" in reply.text
        assert reply.pending_confirmations[0] in reply.text
        assert "nothing has been changed yet" in reply.text


class TestConfirmingInALaterRequest:
    """The answer arrives in its own request, as an API requires."""

    async def test_the_operation_is_performed(self):
        engine, _client, cache = build_engine(labelling_script())
        first = await engine.respond(turn("file the Project Alpha message under Finance"))
        ticket = first.pending_confirmations[0]

        await engine.respond(turn(f"CONFIRM {ticket}"))

        assert LABEL_ID in await labels_of(cache, MESSAGE_ID)

    async def test_nothing_remains_pending(self):
        engine, _client, _cache = build_engine(labelling_script())
        first = await engine.respond(turn("file the Project Alpha message under Finance"))

        second = await engine.respond(turn(f"CONFIRM {first.pending_confirmations[0]}"))

        assert second.pending_confirmations == ()

    async def test_cancelling_changes_nothing(self):
        engine, _client, cache = build_engine(labelling_script())
        first = await engine.respond(turn("file the Project Alpha message under Finance"))

        reply = await engine.respond(turn(f"cancel {first.pending_confirmations[0]}"))

        assert "Nothing was changed" in reply.text
        assert LABEL_ID not in await labels_of(cache, MESSAGE_ID)

    async def test_an_unknown_ticket_is_reported_without_failing(self):
        """The caller did nothing wrong; the conversation should carry on."""
        engine, _client, _cache = build_engine([says("hello")])

        reply = await engine.respond(turn("confirm cfm-deadbeef"))

        assert "not awaiting an answer" in reply.text


@pytest.mark.security
class TestAConfirmationIsNeverGivenToTheModel:
    """The model must not be the authority on whether a side effect happens."""

    async def test_the_model_is_not_consulted_for_a_confirmation(self):
        engine, client, _cache = build_engine(labelling_script())
        first = await engine.respond(turn("file the Project Alpha message under Finance"))
        turns_before = client.turn

        await engine.respond(turn(f"CONFIRM {first.pending_confirmations[0]}"))

        assert client.turn == turns_before

    async def test_a_message_that_merely_mentions_a_ticket_is_an_ordinary_turn(self):
        """Otherwise a quoted identifier in prose could approve an operation."""
        engine, client, cache = build_engine(labelling_script())
        first = await engine.respond(turn("file the Project Alpha message under Finance"))
        ticket = first.pending_confirmations[0]
        client.append(says("I cannot answer that."))

        await engine.respond(turn(f"what would confirm {ticket} actually do?"))

        assert LABEL_ID not in await labels_of(cache, MESSAGE_ID)


@pytest.mark.security
class TestConversationsAreIsolated:
    """State is keyed by the authenticated subject, never by the caller's text."""

    async def test_another_caller_cannot_answer_a_confirmation(self):
        engine, client, cache = build_engine(labelling_script())
        first = await engine.respond(turn("file the Project Alpha message under Finance"))
        ticket = first.pending_confirmations[0]
        client.append(says("nothing to do"))

        reply = await engine.respond(turn(f"CONFIRM {ticket}", principal=BOB))

        assert "not awaiting an answer" in reply.text
        assert LABEL_ID not in await labels_of(cache, MESSAGE_ID)

    async def test_another_conversation_cannot_answer_it(self):
        engine, client, cache = build_engine(labelling_script())
        first = await engine.respond(turn("file the Project Alpha message under Finance"))
        ticket = first.pending_confirmations[0]
        client.append(says("nothing to do"))

        reply = await engine.respond(turn(f"CONFIRM {ticket}", conversation="conv-2"))

        assert "not awaiting an answer" in reply.text
        assert LABEL_ID not in await labels_of(cache, MESSAGE_ID)


class TestAConversationSurvivesBetweenRequests:
    """Otherwise every message would start a new conversation."""

    async def test_two_turns_share_one_runtime(self):
        engine, _client, cache = build_engine([says("first"), says("second")])

        await engine.respond(turn("hello"))
        await engine.respond(turn("again"))

        assert cache.live_conversations == 1

    async def test_two_callers_get_their_own(self):
        engine, client, cache = build_engine([says("first")])
        client.append(says("second"))

        await engine.respond(turn("hello", principal=ADA))
        await engine.respond(turn("hello", principal=BOB))

        assert cache.live_conversations == 2
