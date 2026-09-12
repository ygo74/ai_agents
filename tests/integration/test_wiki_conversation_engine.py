"""Tests of the Wiki Agent answering requests instead of a console.

An HTTP surface asks one thing of the agent: given an authenticated caller, a
conversation identifier and a message, return an answer. These tests drive that
port directly - no web framework involved - because what matters here is the
behaviour, not the transport.

They are the LangGraph counterpart of ``test_conversation_engine.py``, and
deliberately assert the same properties. A confirmation is recognised before the
model is given the turn, a conversation survives between requests, and state is
partitioned by the authenticated subject rather than by the identifier a caller
supplied.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.langgraph_fakes import ScriptedChatModel, ToolCall, calls, says

from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.core.serving.conversation import ConversationTurn
from ai_agent_lab.core.serving.runtimes import ConversationRuntimeCache
from ai_agent_lab.wiki.application.composition import WikiAgentCompositionRoot
from ai_agent_lab.wiki.application.entrypoints.conversation import (
    WikiConversation,
    WikiConversationEngine,
    WikiConversationFactory,
)
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.config.settings import WikiAgentMode, WikiAgentSettings
from ai_agent_lab.wiki.skills.analysis import AnswerOutput

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# `diana` may read every space of the delivered dataset; `alice` may not. The
# pair is what makes a cross-caller test mean something.
DIANA = Principal(subject="diana", display_name="Diana")
ALICE = Principal(subject="alice", display_name="Alice")

PAGE_ID = "apollo-architecture"
COMMENT = "Checked against the delivery plan."


class ScriptedReasoner:
    """Returns a prepared analysis without reaching a model."""

    async def reason(self, request: object, response_model: type) -> object:
        """Return the prepared output whatever was asked."""
        del request, response_model
        return AnswerOutput(answer="scripted", cited_page_ids=[])


def build_engine(
    script: list,
) -> tuple[WikiConversationEngine, ScriptedChatModel, ConversationRuntimeCache[WikiConversation]]:
    """Assemble the engine over a scripted model and the deterministic dataset."""
    model = ScriptedChatModel(script)
    factory = WikiConversationFactory(
        WikiAgentCompositionRoot(
            WikiAgentSettings(mode=WikiAgentMode.MOCK),
            model,
            reasoner=ScriptedReasoner(),
            base_path=REPOSITORY_ROOT,
        )
    )
    cache: ConversationRuntimeCache[WikiConversation] = ConversationRuntimeCache(
        factory.build, WikiConversationFactory.close
    )
    return WikiConversationEngine(cache), model, cache


def turn(message: str, *, principal: Principal = DIANA, conversation: str = "conv-1") -> ConversationTurn:
    """Build one request."""
    return ConversationTurn(principal=principal, conversation_id=conversation, message=message)


def commenting_script() -> list:
    """A model that asks to comment on a page, then reports."""
    return [
        calls(ToolCall(WikiToolName.ADD_COMMENT.value, {"page_id": PAGE_ID, "body": COMMENT})),
        says("I have asked for confirmation."),
    ]


async def comments_of(
    cache: ConversationRuntimeCache[WikiConversation],
    principal: Principal = DIANA,
    conversation: str = "conv-1",
) -> tuple[str, ...]:
    """Read the page's comments back through the same conversation."""
    live = await cache.acquire(principal, conversation)
    comments = await live.runtime.wiki_tools.get_comments(PAGE_ID, live.runtime.user)
    return tuple(comment.body.expose() for comment in comments)


class TestAnOrdinaryTurn:
    """A question is answered and nothing is silently changed."""

    async def test_it_returns_what_the_model_said(self):
        engine, _model, _cache = build_engine([says("The Apollo scope is on the charter page.")])

        reply = await engine.respond(turn("what is in scope for Apollo?"))

        assert "Apollo scope" in reply.text

    async def test_nothing_is_pending_when_nothing_was_gated(self):
        engine, _model, _cache = build_engine([says("Nothing to do.")])

        reply = await engine.respond(turn("hello"))

        assert reply.pending_confirmations == ()
        assert not reply.awaits_confirmation


@pytest.mark.security
class TestAGatedOperationDefersInsteadOfBlocking:
    """A request must be answered, so an approval cannot hold the turn."""

    async def test_the_turn_returns_and_changes_nothing(self):
        engine, _model, cache = build_engine(commenting_script())

        reply = await engine.respond(turn(f"comment on {PAGE_ID}"))

        assert reply.awaits_confirmation
        assert COMMENT not in await comments_of(cache)

    async def test_the_answer_names_what_is_waiting(self):
        """A ticket nobody can quote is a ticket nobody can answer."""
        engine, _model, _cache = build_engine(commenting_script())

        reply = await engine.respond(turn(f"comment on {PAGE_ID}"))

        assert "CONFIRM" in reply.text
        assert reply.pending_confirmations[0] in reply.text
        assert "nothing has been changed yet" in reply.text


class TestConfirmingInALaterRequest:
    """The answer arrives in its own request, as an API requires."""

    async def test_the_operation_is_performed(self):
        engine, _model, cache = build_engine(commenting_script())
        first = await engine.respond(turn(f"comment on {PAGE_ID}"))

        await engine.respond(turn(f"CONFIRM {first.pending_confirmations[0]}"))

        assert COMMENT in await comments_of(cache)

    async def test_nothing_remains_pending(self):
        engine, _model, _cache = build_engine(commenting_script())
        first = await engine.respond(turn(f"comment on {PAGE_ID}"))

        second = await engine.respond(turn(f"CONFIRM {first.pending_confirmations[0]}"))

        assert second.pending_confirmations == ()

    async def test_cancelling_changes_nothing(self):
        engine, _model, cache = build_engine(commenting_script())
        first = await engine.respond(turn(f"comment on {PAGE_ID}"))

        reply = await engine.respond(turn(f"cancel {first.pending_confirmations[0]}"))

        assert "Nothing was changed" in reply.text
        assert COMMENT not in await comments_of(cache)

    async def test_a_ticket_cannot_be_answered_twice(self):
        """One approval authorises one execution, never two."""
        engine, _model, _cache = build_engine(commenting_script())
        first = await engine.respond(turn(f"comment on {PAGE_ID}"))
        ticket = first.pending_confirmations[0]
        await engine.respond(turn(f"CONFIRM {ticket}"))

        replayed = await engine.respond(turn(f"CONFIRM {ticket}"))

        assert "not awaiting an answer" in replayed.text

    async def test_an_unknown_ticket_is_reported_without_failing(self):
        """The caller did nothing wrong; the conversation should carry on."""
        engine, _model, _cache = build_engine([says("hello")])

        reply = await engine.respond(turn("confirm cfm-deadbeef"))

        assert "not awaiting an answer" in reply.text


@pytest.mark.security
class TestAConfirmationIsNeverGivenToTheModel:
    """The model must not be the authority on whether a side effect happens."""

    async def test_the_model_is_not_consulted_for_a_confirmation(self):
        engine, model, _cache = build_engine(commenting_script())
        first = await engine.respond(turn(f"comment on {PAGE_ID}"))
        prompts_before = len(model.prompts)

        await engine.respond(turn(f"CONFIRM {first.pending_confirmations[0]}"))

        assert len(model.prompts) == prompts_before

    async def test_a_message_that_merely_mentions_a_ticket_is_an_ordinary_turn(self):
        """Otherwise a quoted identifier in prose could approve an operation."""
        engine, model, cache = build_engine(commenting_script())
        first = await engine.respond(turn(f"comment on {PAGE_ID}"))
        ticket = first.pending_confirmations[0]
        model.script.append(says("I cannot answer that."))

        await engine.respond(turn(f"what would confirm {ticket} actually do?"))

        assert COMMENT not in await comments_of(cache)


@pytest.mark.security
class TestConversationsAreIsolated:
    """State is keyed by the authenticated subject, never by the caller's text."""

    async def test_another_caller_cannot_answer_a_confirmation(self):
        engine, model, cache = build_engine(commenting_script())
        first = await engine.respond(turn(f"comment on {PAGE_ID}"))
        ticket = first.pending_confirmations[0]
        model.script.append(says("nothing to do"))

        reply = await engine.respond(turn(f"CONFIRM {ticket}", principal=ALICE))

        assert "not awaiting an answer" in reply.text
        assert COMMENT not in await comments_of(cache)

    async def test_another_caller_sees_nothing_pending(self):
        engine, model, _cache = build_engine(commenting_script())
        await engine.respond(turn(f"comment on {PAGE_ID}"))
        model.script.append(says("nothing to do"))

        reply = await engine.respond(turn("anything waiting?", principal=ALICE))

        assert reply.pending_confirmations == ()

    async def test_two_callers_get_their_own_runtime(self):
        """Sharing one would serve the second caller the first one's wiki."""
        engine, model, cache = build_engine([says("first")])
        await engine.respond(turn("hello"))
        model.script.append(says("second"))

        await engine.respond(turn("hello", principal=ALICE))

        assert cache.live_conversations == 2

    async def test_one_caller_continues_the_same_conversation(self):
        """Otherwise every message would start a new one."""
        engine, model, cache = build_engine([says("first")])
        await engine.respond(turn("hello"))
        model.script.append(says("second"))

        await engine.respond(turn("and again"))

        assert cache.live_conversations == 1
