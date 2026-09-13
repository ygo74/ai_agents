"""Tests of the Wiki Agent served over HTTP.

These drive the **real** service factory - the same ``build_app`` a deployment
runs - through the real runtime routes, with only the model replaced. Building
the application by hand here would test a copy of the composition rather than
the composition, and the authentication posture is precisely what must not be
tested on a copy.

The runtime's two known gaps are probed rather than pinned to a version, exactly
as the Mail Agent's contract test does: the suite then tells the truth against
both the published release and a patched checkout, and starts enforcing each
contract the moment it becomes available.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.support.langgraph_fakes import ScriptedChatModel, ToolCall, calls, says

from ai_agent_lab.wiki.application.entrypoints.service import (
    AGENT_ID,
    WikiServiceConfigurationError,
    build_app,
)
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.skills.analysis import AnswerOutput

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

API_KEY = "demo-key-for-tests"
MODEL = AGENT_ID
PAGE_ID = "apollo-architecture"
COMMENT = "Checked against the delivery plan."

NOT_OPENAI_YET = (
    "the installed ygo74-agent-runtime answers with its exchange envelope rather "
    "than a chat.completion object; LibreChat needs the OpenAI shape"
)

NO_HEADER_FORWARDING = (
    "the installed ygo74-agent-runtime does not carry request headers into the "
    "uniform payload, so a conversation identifier cannot reach the agent"
)


def _maps_to_openai() -> bool:
    """Whether the installed runtime renders an OpenAI-shaped response."""
    from ygo74.agent_runtime.domains.mapping.response_mapper import map_response

    rendered = map_response(
        "openai.chat_completions",
        {"request_id": "probe", "status": "success", "output": "ok"},
    )
    return rendered.get("object") == "chat.completion"


def _forwards_the_conversation() -> bool:
    """Whether the installed runtime carries a conversation header to the handler."""
    try:
        from ygo74.agent_runtime.domains.endpoints.header_forwarding import RequestHeaderForwarder
    except ImportError:
        return False

    carried = RequestHeaderForwarder.create().apply({}, {"x-conversation-id": "probe"})
    return carried.get("conversation_id") == "probe"


maps_to_openai = _maps_to_openai()
forwards_the_conversation = _forwards_the_conversation()


class ScriptedReasoner:
    """Returns a prepared analysis without reaching a model."""

    async def reason(self, request: object, response_model: type) -> object:
        """Return the prepared output whatever was asked."""
        del request, response_model
        return AnswerOutput(answer="scripted", cited_page_ids=[])


@pytest.fixture(autouse=True)
def demonstration_deployment(monkeypatch):
    """Configure the single-caller posture the whole module is written against."""
    monkeypatch.setenv("WIKI_AGENT_MODE", "mock")
    monkeypatch.setenv("WIKI_AGENT_USER_ID", "diana")
    monkeypatch.setenv("WIKI_AGENT_HTTP_API_KEY", API_KEY)
    monkeypatch.delenv("WIKI_AGENT_HTTP_OIDC_ISSUER", raising=False)


def build_service(script) -> tuple[object, ScriptedChatModel]:
    """Assemble the real HTTP application over a scripted model."""
    model = ScriptedChatModel(script)
    app = build_app(base_path=REPOSITORY_ROOT, chat_model=model)
    return app, model


def chat(http: TestClient, message: str, *, key: str | None = API_KEY, conversation: str | None = None):
    """Post one OpenAI chat completion, the way LibreChat does."""
    headers = {} if key is None else {"x-api-key": key}
    if conversation is not None:
        headers["X-Conversation-Id"] = conversation
    return http.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": message}], "stream": False},
        headers=headers,
    )


def ticket_in(reply: str) -> str:
    """Read the ticket a reply offers, the way a user copies it."""
    match = re.search(r"cfm-[0-9a-f]+", reply)
    assert match is not None, reply
    return match.group(0)


def answer_of(response) -> str:
    """Read the agent's text out of whatever shape the runtime returned."""
    body = response.json()
    if "choices" in body:
        return str(body["choices"][0]["message"]["content"])
    return str(body.get("output", ""))


def commenting_script() -> list:
    """A model that asks to comment on a page, then reports."""
    return [
        calls(ToolCall(WikiToolName.ADD_COMMENT.value, {"page_id": PAGE_ID, "body": COMMENT})),
        says("I have asked for confirmation."),
    ]


def _user_text(model: ScriptedChatModel) -> str:
    """Everything the scripted model was given as user text."""
    return "\n".join(
        str(getattr(message, "content", ""))
        for prompt in model.prompts
        for message in prompt
        if type(message).__name__ == "HumanMessage"
    )


class TestTheEndpointAnswers:
    """What works today, end to end, through the real routes."""

    def test_a_request_is_answered(self):
        app, _model = build_service([says("The Apollo scope is on the charter page.")])

        with TestClient(app) as http:
            response = chat(http, "what is in scope for Apollo?")

        assert response.status_code == 200
        assert "Apollo scope" in answer_of(response)

    def test_the_agent_is_discoverable_as_a_model(self):
        """LibreChat lists it, and the description comes from `config/`."""
        app, _model = build_service([says("hello")])

        with TestClient(app) as http:
            body = http.get("/v1/models", headers={"x-api-key": API_KEY}).json()

        assert any(entry["id"] == AGENT_ID for entry in body["data"])

    def test_only_the_latest_turn_reaches_the_agent(self):
        """LibreChat re-sends the whole conversation; replaying it would duplicate."""
        app, model = build_service([says("first")])

        with TestClient(app) as http:
            http.post(
                "/v1/chat/completions",
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi"},
                        {"role": "user", "content": "which pages are stale?"},
                    ],
                },
                headers={"x-api-key": API_KEY},
            )

        seen = _user_text(model)
        assert "which pages are stale?" in seen
        assert "hello" not in seen


class TestTheServiceRefusesToRunOpen:
    """A wiki service with no caller would serve restricted spaces to anyone."""

    def test_it_will_not_start_without_a_way_to_identify_a_caller(self, monkeypatch):
        monkeypatch.delenv("WIKI_AGENT_HTTP_API_KEY", raising=False)
        monkeypatch.setenv("WIKI_AGENT_HTTP_API_KEY", "")

        with pytest.raises(WikiServiceConfigurationError, match="needs a caller"):
            build_app(base_path=REPOSITORY_ROOT, chat_model=ScriptedChatModel([says("hello")]))


@pytest.mark.skipif(not maps_to_openai, reason=NOT_OPENAI_YET)
class TestOpenAiWireCompatibility:
    """The shape LibreChat actually needs."""

    def test_the_body_is_a_chat_completion(self):
        app, _model = build_service([says("hello")])

        with TestClient(app) as http:
            body = chat(http, "hi").json()

        assert body["object"] == "chat.completion"

    def test_the_answer_sits_in_a_choice(self):
        app, _model = build_service([says("hello there")])

        with TestClient(app) as http:
            body = chat(http, "hi").json()

        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["message"]["content"] == "hello there"


@pytest.mark.skipif(not forwards_the_conversation, reason=NO_HEADER_FORWARDING)
class TestEachDiscussionGetsItsOwnSession:
    """LibreChat opens a discussion per conversation; the agent must follow."""

    def test_two_conversations_do_not_share_a_session(self):
        app, _model = build_service([says("first"), says("second")])

        with TestClient(app) as http:
            chat(http, "what is in scope?", conversation="conv-a")
            chat(http, "which pages are stale?", conversation="conv-b")

            # Inside the client, deliberately: leaving it releases every open
            # conversation, which is the behaviour the service is built for.
            assert app.state.conversations.live_conversations == 2

    def test_the_same_conversation_is_continued(self):
        app, _model = build_service([says("first"), says("second")])

        with TestClient(app) as http:
            chat(http, "what is in scope?", conversation="conv-a")
            chat(http, "and after that?", conversation="conv-a")

            assert app.state.conversations.live_conversations == 1

    def test_leaving_the_service_releases_every_conversation(self):
        """Shutdown must not leave an MCP session open behind a dead process."""
        app, _model = build_service([says("first")])

        with TestClient(app) as http:
            chat(http, "what is in scope?", conversation="conv-a")

        assert app.state.conversations.live_conversations == 0

    def test_a_confirmation_cannot_be_answered_from_another_conversation(self):
        """A ticket belongs to one conversation, and a discussion is one."""
        app, _model = build_service([*commenting_script(), says("nothing pending here")])

        with TestClient(app) as http:
            raised = answer_of(chat(http, f"comment on {PAGE_ID}", conversation="conv-a"))
            ticket = ticket_in(raised)
            elsewhere = answer_of(chat(http, f"CONFIRM {ticket}", conversation="conv-b"))

        assert "not awaiting an answer" in elsewhere


@pytest.mark.security
class TestAnUnauthenticatedCallerIsRefused:
    """Without a subject there is nothing to partition state by."""

    def test_a_request_without_a_key_is_rejected(self):
        app, _model = build_service([says("hello")])

        with TestClient(app) as http:
            response = chat(http, "what is in scope?", key=None)

        assert response.status_code in (401, 403)

    def test_a_wrong_key_is_rejected(self):
        app, _model = build_service([says("hello")])

        with TestClient(app) as http:
            response = chat(http, "what is in scope?", key="not-the-key")

        assert response.status_code in (401, 403)

    def test_the_model_is_never_reached_without_authentication(self):
        """Refusing after asking a model would still have spent money and data."""
        app, model = build_service([says("hello")])

        with TestClient(app) as http:
            chat(http, "what is in scope?", key=None)

        assert model.prompts == []

    def test_discovery_is_not_public(self):
        """Listing the agent lists every capability it has."""
        app, _model = build_service([says("hello")])

        with TestClient(app) as http:
            response = http.get("/v1/models")

        assert response.status_code in (401, 403)


@pytest.mark.security
class TestAGatedOperationIsDeferredOverHttp:
    """A request must be answered, so an approval cannot hold the connection."""

    def test_the_turn_returns_a_ticket_instead_of_writing(self):
        app, _model = build_service(commenting_script())

        with TestClient(app) as http:
            reply = answer_of(chat(http, f"comment on {PAGE_ID}"))

        assert "CONFIRM" in reply
        assert "nothing has been changed yet" in reply

    def test_the_ticket_can_be_answered_in_a_later_request(self):
        app, _model = build_service(commenting_script())

        with TestClient(app) as http:
            raised = answer_of(chat(http, f"comment on {PAGE_ID}"))
            confirmed = answer_of(chat(http, f"CONFIRM {ticket_in(raised)}"))

        assert "not awaiting an answer" not in confirmed

    def test_an_unknown_ticket_does_not_fail_the_conversation(self):
        app, _model = build_service([says("hello")])

        with TestClient(app) as http:
            response = chat(http, "CONFIRM cfm-deadbeef")

        assert response.status_code == 200
        assert "not awaiting an answer" in answer_of(response)
