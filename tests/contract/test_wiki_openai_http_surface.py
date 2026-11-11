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

import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
import yaml
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel
from tests.support.langgraph_fakes import ScriptedChatModel, ToolCall, calls, says
from tests.support.mcp_http import connected_mcp_session, invoke_agent
from ygo74.agent_runtime.domains.configuration.directory import CONFIG_DIR_VARIABLE

from ai_agent_lab.wiki.adapters.capabilities.write_capabilities import DRAFT_PAGE_CONTENT
from ai_agent_lab.wiki.application.skills.analysis import AnswerOutput
from ai_agent_lab.wiki.bootstrap.service import (
    AGENT_ID,
    WikiServiceConfigurationError,
    build_app,
)
from ai_agent_lab.wiki.domain.operation_names import WikiToolName
from ai_agent_lab.wiki.infrastructure.inmemory.wiki_tools import InMemoryWikiTools

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
JWT_SIGNING_KEY = "wiki-agent-contract-test-signing-key"
JWT_ISSUER = "https://identity.example.test/agents"
JWT_AUDIENCE = "wiki-agent-contract-test"

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
    from ygo74.agent_runtime.domains.contracts.agent_output import AgentOutput, TextContent
    from ygo74.agent_runtime.domains.mapping.response_mapper import map_response

    rendered = map_response(
        "openai.chat_completions",
        AgentOutput(contents=(TextContent("ok"),)),
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


class StreamingStructuredModel(ScriptedChatModel):
    """Run a real nested chat-model call before parsing its structured response."""

    def with_structured_output(self, schema: type[BaseModel], **kwargs: object):
        del kwargs
        return self | RunnableLambda(lambda message: schema.model_validate_json(message.content))


@pytest.fixture(autouse=True)
def demonstration_deployment(monkeypatch, tmp_path):
    """Configure the single-caller posture the whole module is written against."""
    monkeypatch.setenv("WIKI_AGENT_MODE", "mock")
    monkeypatch.setenv("WIKI_AGENT_USER_ID", "diana")
    monkeypatch.setenv("WIKI_AGENT_HTTP_API_KEY", API_KEY)
    monkeypatch.delenv("WIKI_AGENT_HTTP_OIDC_ISSUER", raising=False)
    config_root = tmp_path / "config"
    shutil.copytree(REPOSITORY_ROOT / "config", config_root)
    monkeypatch.setenv(CONFIG_DIR_VARIABLE, str(config_root))


def build_service(script) -> tuple[object, ScriptedChatModel]:
    """Assemble the real HTTP application over a scripted model."""
    model = ScriptedChatModel(script)
    app = build_app(base_path=REPOSITORY_ROOT, chat_model=model)
    return app, model


def chat(
    http: TestClient,
    message: str,
    *,
    key: str | None = API_KEY,
    conversation: str | None = None,
    stream: bool = False,
):
    """Post one OpenAI chat completion, the way LibreChat does."""
    headers = {} if key is None else {"x-api-key": key}
    if conversation is not None:
        headers["X-Conversation-Id"] = conversation
    return http.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": message}], "stream": stream},
        headers=headers,
    )


def streamed_answer_of(response: httpx.Response) -> str:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = []
    for line in response.text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        event = json.loads(line.removeprefix("data: "))
        for choice in event.get("choices", []):
            chunks.append(choice.get("delta", {}).get("content") or "")
    return "".join(chunks)


def assert_complete_tool_history(model: ScriptedChatModel) -> None:
    for prompt in model.prompts:
        pending: set[str] = set()
        for message in prompt:
            if isinstance(message, ToolMessage):
                assert message.tool_call_id in pending
                pending.remove(message.tool_call_id)
                continue
            assert not pending, "A new message precedes outstanding tool responses"
            if isinstance(message, AIMessage):
                pending.update(call["id"] for call in message.tool_calls)
        assert not pending


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


def _configure_static_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a local signer to exercise Wiki's subject-only MCP identity."""
    configuration_root = Path(os.environ[CONFIG_DIR_VARIABLE])
    manifest_path = configuration_root / "agents" / "wiki" / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["http"]["mcp"] = {"resource_url": "${WIKI_AGENT_HTTP_MCP_RESOURCE_URL}"}
    manifest["http"]["security"] = {
        "mode": "jwt",
        "jwt": {
            "issuer": JWT_ISSUER,
            "audience": JWT_AUDIENCE,
            "secret": "${WIKI_AGENT_HTTP_JWT_SECRET}",
            "allowed_algorithms": ["HS256"],
        },
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("WIKI_AGENT_HTTP_JWT_SECRET", JWT_SIGNING_KEY)
    monkeypatch.setenv(
        "WIKI_AGENT_HTTP_MCP_RESOURCE_URL",
        "https://wiki.example.test/mcp",
    )


def _access_token(subject: str) -> str:
    """Sign a short-lived test token without an email claim."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        JWT_SIGNING_KEY,
        algorithm="HS256",
    )


def _mcp_text(result) -> str:
    """Read visible text from the typed output returned by the MCP operation."""
    output = result.structuredContent["output"]["value"]["contents"]
    return "\n".join(entry["value"]["text"] for entry in output if entry["type"] == "text")


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

        with pytest.raises(
            WikiServiceConfigurationError,
            match=r"http\.security\.api_key\.value",
        ):
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

    async def test_manifest_disables_endpoints_that_are_not_declared(self):
        app, _model = build_service([says("hello")])

        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as http,
        ):
            responses = await http.post(
                "/v1/responses",
                json={"model": MODEL, "input": "hi"},
                headers={"x-api-key": API_KEY},
            )
            messages = await http.post(
                "/v1/messages",
                json={},
                headers={"x-api-key": API_KEY},
            )

        assert responses.status_code == 404
        assert messages.status_code == 404


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
class TestInternalReasoningIsNotDisplayed:
    @pytest.mark.parametrize("stream", [False, True])
    @pytest.mark.parametrize("answer", ["Here is the proposed Live test section.", '{"status":"draft_ready"}'])
    def test_drafting_returns_only_the_assistant_answer(self, stream, answer):
        internal = json.dumps({"title": "Architecture overview", "body": "Internal draft body."})
        model = StreamingStructuredModel(
            [
                calls(ToolCall(DRAFT_PAGE_CONTENT, {"page_id": PAGE_ID, "instruction": "Add a Live test section"})),
                says(internal),
                says(answer),
            ]
        )
        app = build_app(base_path=REPOSITORY_ROOT, chat_model=model)

        with TestClient(app) as http:
            response = chat(http, "Prepare a revision of the architecture page", stream=stream)
            rendered = streamed_answer_of(response) if stream else answer_of(response)

        assert len(model.prompts) == 3
        assert "draft_reference" in str(model.prompts[-1][-1].content)
        assert rendered == answer
        assert internal not in rendered
        assert "Internal draft body." not in rendered


@pytest.mark.security
class TestAGatedOperationIsDeferredOverHttp:
    """A request must be answered, so an approval cannot hold the connection."""

    def test_the_turn_returns_a_ticket_instead_of_writing(self):
        app, _model = build_service(commenting_script())

        with TestClient(app) as http:
            reply = answer_of(chat(http, f"comment on {PAGE_ID}"))

        assert "CONFIRM" in reply
        assert "nothing has been changed yet" in reply

    @pytest.mark.parametrize("stream_follow_up", [False, True])
    def test_streamed_ticket_preserves_history_without_writing(self, monkeypatch, stream_follow_up):
        write = AsyncMock()
        monkeypatch.setattr(InMemoryWikiTools, "add_comment", write)
        app, model = build_service([*commenting_script(), says("The comment is awaiting confirmation.")])

        with TestClient(app) as http:
            raised = streamed_answer_of(chat(http, f"comment on {PAGE_ID}", conversation="streamed", stream=True))
            assert ticket_in(raised)
            assert "nothing has been changed yet" in raised
            assert '"tool_call_id"' not in raised
            write.assert_not_awaited()

            response = chat(http, "What is awaiting confirmation?", conversation="streamed", stream=stream_follow_up)
            continued = streamed_answer_of(response) if stream_follow_up else answer_of(response)

        assert "awaiting confirmation" in continued
        assert len(model.prompts) == 3
        assert_complete_tool_history(model)
        write.assert_not_awaited()

    @pytest.mark.parametrize("decision", ["CONFIRM", "CANCEL"])
    @pytest.mark.parametrize("stream_confirmation", [False, True])
    def test_streamed_ticket_is_resolved_once_outside_the_model(self, decision, stream_confirmation):
        app, model = build_service(commenting_script())
        with (
            patch.object(
                InMemoryWikiTools, "add_comment", autospec=True, side_effect=InMemoryWikiTools.add_comment
            ) as write,
            TestClient(app) as http,
        ):
            raised = streamed_answer_of(chat(http, f"comment on {PAGE_ID}", conversation="streamed", stream=True))
            ticket = ticket_in(raised)
            write.assert_not_awaited()
            prompts_before = len(model.prompts)

            response = chat(http, f"{decision} {ticket}", conversation="streamed", stream=stream_confirmation)
            resolved = streamed_answer_of(response) if stream_confirmation else answer_of(response)
            replayed = answer_of(chat(http, f"CONFIRM {ticket}", conversation="streamed"))

            if decision == "CONFIRM":
                write.assert_awaited_once()
                assert "Comment posted successfully." in resolved
                assert "UNTRUSTED_" not in resolved
                assert '"comment_id"' not in resolved
            else:
                write.assert_not_awaited()
                assert "Nothing was changed" in resolved

        assert "not awaiting an answer" not in resolved
        assert "not awaiting an answer" in replayed
        assert len(model.prompts) == prompts_before
        assert_complete_tool_history(model)

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


@pytest.mark.security
async def test_mcp_accepts_subject_only_identity_and_isolates_same_conversation_by_caller(
    monkeypatch,
):
    """Wiki accepts account subjects without email and never shares caller state."""
    _configure_static_jwt(monkeypatch)
    app, model = build_service([says("first caller answer"), says("second caller answer")])

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent.test",
            headers={"authorization": f"Bearer {_access_token('wiki-user-one')}"},
        ) as http:
            models = await http.get("/v1/models")

        async with connected_mcp_session(
            app,
            {"authorization": f"Bearer {_access_token('wiki-user-one')}"},
        ) as first_session:
            tools = await first_session.list_tools()
            first = await invoke_agent(
                first_session,
                "private page phrase for wiki user one",
                conversation_id="same-thread",
            )

        async with connected_mcp_session(
            app,
            {"authorization": f"Bearer {_access_token('wiki-user-two')}"},
        ) as second_session:
            second = await invoke_agent(
                second_session,
                "private page phrase for wiki user two",
                conversation_id="same-thread",
            )

        assert len(tools.tools) == 1
        assert models.status_code == 200
        assert set(tools.tools[0].inputSchema["properties"]) == {
            "message",
            "conversation_id",
        }
        assert first.isError is False
        assert second.isError is False
        assert app.state.conversations.live_conversations == 2

    second_prompt = "\n".join(str(message) for message in model.prompts[1])
    assert "private page phrase for wiki user one" not in second_prompt


@pytest.mark.security
async def test_mcp_keeps_wiki_write_confirmation_before_mutation():
    """An MCP turn returns the existing confirmation ticket without writing."""
    app, model = build_service(commenting_script())

    with patch.object(
        InMemoryWikiTools,
        "add_comment",
        autospec=True,
        side_effect=InMemoryWikiTools.add_comment,
    ) as confirmed_write:
        async with (
            app.router.lifespan_context(app),
            connected_mcp_session(
                app,
                {"x-api-key": API_KEY},
            ) as session,
        ):
            raised = await invoke_agent(
                session,
                f"comment on {PAGE_ID}",
                conversation_id="confirmation-thread",
            )
            reply = _mcp_text(raised)
            assert raised.isError is False
            assert raised.structuredContent["metadata"]["pending_confirmations"]
            assert "nothing has been changed yet" in reply
            ticket = ticket_in(reply)
            confirmed_write.assert_not_awaited()

            confirmed = await invoke_agent(
                session,
                f"CONFIRM {ticket}",
                conversation_id="confirmation-thread",
            )
            assert confirmed.isError is False
            assert "Comment posted successfully." in _mcp_text(confirmed)
            confirmed_write.assert_awaited_once()

        assert len(model.prompts) == 2
