"""Tests of the Mail Agent served over HTTP.

These drive the real FastAPI application through the real runtime routes, with
only the model replaced.

One finding is pinned here deliberately. ``ygo74-agent-runtime`` 0.0.2 normalises
an **OpenAI-shaped request** but answers with its own exchange envelope
(``{request_id, status, endpoint_type, output}``) rather than a
``chat.completion`` object. An OpenAI client - LibreChat included - cannot parse
that, so the wire-compatibility tests below are marked as expected failures.
They are written against the shape LibreChat needs, so that fixing the mapping
upstream turns them green and says so loudly.

Everything the application owns - authentication, attribution, deferral of gated
operations - is verified against what works today.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from agent_framework.openai import OpenAIChatClient
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import APIError, AsyncOpenAI, OpenAI
from tests.support.maf_fakes import ScriptedChatClient, ToolCall, calls, says
from tests.support.mail_continuity_provider import ContextualResponsesProvider, bounded_mailbox
from ygo74.agent_runtime.domains.auth.apikey_authenticator import StaticApiKeyUserResolver
from ygo74.agent_runtime.domains.auth.auth_context import ResolvedUser
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.discovery.agent_descriptor import AgentDescriptor
from ygo74.agent_runtime.domains.discovery.descriptor_registry import DescriptorRegistry
from ygo74.agent_runtime.domains.discovery.discovery_configuration import DiscoveryConfiguration
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import AdvertisedSecurity
from ygo74.agent_runtime.domains.endpoints.fastapi_endpoints import add_ai_endpoints
from ygo74.agent_runtime.domains.sessions.conversation_cache import ConversationRuntimeCache

from ai_agent_lab.mail.adapters.http.entrypoint import (
    MailAgentDescriptorFactory,
    MailAgentEntrypoint,
)
from ai_agent_lab.mail.bootstrap.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.bootstrap.conversation import (
    MailConversation,
    MailConversationEngine,
    MailConversationFactory,
)
from ai_agent_lab.mail.domain.operation_names import MailToolName
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentSettings
from ai_agent_lab.mail.infrastructure.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mail.infrastructure.inmemory.reasoner import ScriptedTextReasoner
from ai_agent_lab.mail.infrastructure.mcp.configuration import load_configuration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

AGENT_ID = "mail-agent"
API_KEY = "demo-key-for-tests"
MODEL = "mail-agent"
MESSAGE_ID = "m-alpha-1"
LABEL_ID = "FINANCE"

NOT_OPENAI_YET = (
    "the installed ygo74-agent-runtime answers with its exchange envelope rather "
    "than a chat.completion object; LibreChat needs the OpenAI shape"
)

NO_HEADER_FORWARDING = (
    "the installed ygo74-agent-runtime does not carry request headers into the "
    "uniform payload, so a conversation identifier cannot reach the agent"
)


def _maps_to_openai() -> bool:
    """Whether the installed runtime renders an OpenAI-shaped response.

    Checked at runtime rather than pinned to a version: the fix is being
    contributed upstream, and this makes the suite tell the truth against both
    the published release and a patched checkout.
    """
    from ygo74.agent_runtime.domains.contracts.agent_output import AgentOutput, TextContent
    from ygo74.agent_runtime.domains.contracts.exchange_models import StandardExchangeResponse
    from ygo74.agent_runtime.domains.mapping.response_mapper import map_response

    rendered = map_response(
        "openai.chat_completions",
        StandardExchangeResponse(
            request_id="probe",
            status="success",
            output=AgentOutput(contents=(TextContent("ok"),)),
        ),
    )
    return rendered.get("object") == "chat.completion"


def _forwards_the_conversation() -> bool:
    """Whether the installed runtime carries a conversation header to the handler.

    Probed the same way and for the same reason: without it every LibreChat
    discussion of one caller collapses into a single session, and that is worth
    reporting as a skip rather than passing quietly.
    """
    try:
        from ygo74.agent_runtime.domains.endpoints.header_forwarding import RequestHeaderForwarder
    except ImportError:
        return False

    carried = RequestHeaderForwarder.create().apply({}, {"x-conversation-id": "probe"})
    return carried.get("conversation_id") == "probe"


maps_to_openai = _maps_to_openai()
forwards_the_conversation = _forwards_the_conversation()


def build_service(script) -> tuple[FastAPI, ScriptedChatClient]:
    """Assemble the real HTTP application over a scripted model."""
    client = ScriptedChatClient(script)
    return build_service_with_client(client), client


def build_service_with_client(client, mail_tools=None, *, enable_responses: bool = False) -> FastAPI:
    """Keep endpoint/auth/cache wiring identical for scripted and SDK clients."""
    composition = MailAgentCompositionRoot(
        MailAgentSettings(always_confirm_tools=MailToolName.APPLY_LABEL.value),
        client,
        reasoner=ScriptedTextReasoner({}),
        mail_tools=mail_tools,
        base_path=REPOSITORY_ROOT,
    )
    factory = MailConversationFactory(composition)
    conversations: ConversationRuntimeCache[MailConversation] = ConversationRuntimeCache(
        factory.build, MailConversationFactory.close
    )

    app = FastAPI()
    # Mirrors the real service, so a test can observe how many conversations the
    # requests it made actually created.
    app.state.conversations = conversations
    api_key_resolver = StaticApiKeyUserResolver(
        {
            API_KEY: ResolvedUser(
                user_id="local-user",
                email="local-user@example.com",
                name="Local User",
            )
        }
    )
    descriptor = MailAgentDescriptorFactory(
        composition.manifest(),
        # The same resolver the endpoints authenticate with, so the descriptor
        # this harness publishes describes this harness.
        security=AdvertisedSecurity.of(jwt_validation=None, api_key_resolver=api_key_resolver),
        agent_id=AGENT_ID,
    ).build()
    app.state.descriptor = descriptor
    add_ai_endpoints(
        app,
        MailAgentEntrypoint(MailConversationEngine(conversations)),
        default_route_key=AGENT_ID,
        enable_openai_chat_completions=True,
        enable_openai_responses=enable_responses,
        require_bearer_token=True,
        api_key_resolver=api_key_resolver,
        descriptor_registry=DescriptorRegistry([descriptor]),
        discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
    )
    return app


def wire_answer(response, stream):
    """Read real OpenAI JSON or completed SSE deltas, including pending tickets."""
    assert response.status_code == 200, response.text
    if not stream:
        assert response.json()["object"] == "chat.completion"
        return answer_of(response)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text
    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    return "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)


@pytest.mark.scenario
@pytest.mark.parametrize("modes", [(False, False), (True, True), (False, True), (True, False)])
def test_title_free_sdk_http_followup_reuses_bounded_table_and_exact_tickets(modes):
    """Two complete LibreChat payloads use provider scope, never a canned follow-up.

    Only synthetic fixtures and an in-process provider transport are used.
    No title request, real LibreChat, live inference or mailbox write is claimed.
    """
    provider = ContextualResponsesProvider()
    mailbox = bounded_mailbox(REPOSITORY_ROOT)
    initial_messages = mailbox.messages
    model_http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    sdk = AsyncOpenAI(api_key="synthetic-test-key", base_url="https://provider.invalid/v1", http_client=model_http)
    model = OpenAIChatClient(model="controlled-model", async_client=sdk)
    app = build_service_with_client(model, InMemoryMailTools({"local-user": mailbox}))
    question = (
        "Nous sommes le 10/10/2026. Analyse les mails du 04/10/2026 au 10/10/2026 inclus "
        "et propose leur classement dans les catégories existantes, en tableaux. N'effectue aucune modification."
    )
    followup = "peux tu classer les mails dans les categories existantes"
    headers = {"x-api-key": API_KEY, "X-Conversation-Id": "conv-bounded-http"}
    with TestClient(app) as http:
        first = wire_answer(http.post("/v1/chat/completions", headers=headers, json={
            "model": MODEL, "stream": modes[0], "messages": [{"role": "user", "content": question}],
        }), modes[0])
        assert "04/10/2026 au 10/10/2026 inclus (7 jours)" in first
        rows = re.findall(r"\| (controlled-\d+) \| (PROJECT_ALPHA|FINANCE|Non classé) \|", first)
        assert len(rows) == 15 and len({message for message, _ in rows}) == 15
        assert first.count("Non classé") == 5 and "outside-" not in first
        second = wire_answer(http.post("/v1/chat/completions", headers=headers, json={
            "model": MODEL, "stream": modes[1], "messages": [
                {"role": "user", "content": question}, {"role": "assistant", "content": first},
                {"role": "user", "content": followup},
            ],
        }), modes[1])
        assert "10 affectations" in second and "CONFIRM cfm-" in second
        assert "Périmètre précédent indisponible" not in second
        assert app.state.conversations.live_conversations == 1

        async def pending_arguments():
            from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal

            principal = AgentPrincipal(subject="local-user", email="local-user@example.com", display_name="Local User")
            async with app.state.conversations.lease(principal, "conv-bounded-http") as conversation:
                pending = conversation.store.pending(subject="local-user", conversation_id="conv-bounded-http")
                return [(item.arguments["message_id"], item.arguments["label_id"]) for item in pending]

        pending = http.portal.call(pending_arguments)
        assert set(pending) == {(message, category) for message, category in rows if category != "Non classé"}
        assert len(pending) == 10
        assert mailbox.messages == initial_messages
        http.portal.call(sdk.close)
        http.portal.call(app.state.conversations.aclose)

    requests = provider.requests
    assert len(requests) == 4  # read/subrun + table; approval/subrun + pending summary
    assert [item.get("previous_response_id") for item in requests] == [
        None, "resp_scope_1", "resp_scope_2", "resp_scope_3",
    ]
    assert all(item.get("store") is not False for item in requests)
    assert [item["stream"] for item in requests] == [modes[0], modes[0], modes[1], modes[1]]
    assert [item["role"] for item in requests[2]["input"]] == ["user"]
    assert question not in json.dumps(requests[2]["input"])
    assert first not in json.dumps(requests[2]["input"])
    prior = provider.effective_histories[2]
    assert sum(item.get("role") == "user" for item in prior) == 2
    assert sum("7 jours" in provider._text(item) for item in prior) == 1
    searches = [item for item in prior if item.get("type") == "function_call" and item["name"] == "search_mail"]
    assert len(searches) == 1
    assert json.loads(searches[0]["arguments"]) == {
        "date_from": "2026-10-04T00:00:00+00:00",
        "date_to": "2026-10-10T23:59:59.999999+00:00", "limit": 50,
    }


def test_contextual_provider_cannot_classify_followup_without_stored_scope():
    """Negative control: the deterministic model genuinely needs prior proposals."""
    provider = ContextualResponsesProvider()
    response = provider(httpx.Request("POST", "https://provider.invalid/v1/responses", json={
        "input": [{"role": "user", "content": "peux tu classer les mails dans les categories existantes"}],
    })).json()
    assert all(item["type"] == "message" for item in response["output"])
    assert "Périmètre précédent indisponible" in response["output"][0]["content"][0]["text"]


@pytest.mark.parametrize("stream", [False, True])
def test_two_http_turns_correlate_safe_session_and_cache_diagnostics(stream, caplog):
    """The same LibreChat handle reuses context with no raw identifiers in added logs.

    Args:
        stream: Real native response mode.
        caplog: Captured safe correlation events.
    """
    import logging

    app, model = build_service([says("controlled first answer"), says("controlled second answer")])
    with caplog.at_level(logging.INFO), TestClient(app) as http:
        for message in ("controlled first question", "controlled follow-up"):
            response = http.post(
                "/v1/chat/completions",
                headers={"x-api-key": API_KEY, "X-Conversation-Id": "sensitive-conversation"},
                json={"model": MODEL, "stream": stream, "messages": [{"role": "user", "content": message}]},
            )
            assert response.status_code == 200
    assert len(model.received_messages[1]) == 3, [
        (record.msg, getattr(record, "phase", None), getattr(record, "reason", None))
        for record in caplog.records if "continuity" in str(record.msg)
    ]
    cache = [record for record in caplog.records if record.msg == "conversation cache continuity"]
    sessions = [record for record in caplog.records if record.msg == "native session continuity"]
    assert cache[0].phase == "create" and cache[1].phase == "hit"
    assert cache[0].cache_instance == cache[1].cache_instance
    after = [record for record in sessions if record.phase == "after"]
    assert [record.turn for record in after] == [1, 2]
    assert len({record.session_instance for record in after}) == 1
    assert after[0].request_fingerprint != after[1].request_fingerprint
    assert all(record.request_fingerprint for record in after)
    assert after[0].conversation_fingerprint == cache[0].conversation_fingerprint
    serialized = repr([record.__dict__ for record in cache + sessions])
    assert "sensitive-conversation" not in serialized
    assert API_KEY not in serialized
    assert "controlled first question" not in serialized


def _only_descriptor(app: FastAPI) -> AgentDescriptor:
    """Return the descriptor this harness registered.

    Read from the object the harness built rather than from the discovery
    payload: the projection onto the OpenAI model shape drops the security
    schemes, and those are exactly what these tests are about.
    """
    descriptor = app.state.descriptor
    assert isinstance(descriptor, AgentDescriptor)
    return descriptor


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


def ticket_in(reply: str) -> str:
    """Read the ticket a reply offers, the way a user copies it.

    Deliberately not a `split` on whitespace: the instruction is rendered as
    markdown, so this asserts that what the interface displays can actually be
    read back.
    """
    match = re.search(r"cfm-[0-9a-f]+", reply)
    assert match is not None, reply
    return match.group(0)


def answer_of(response) -> str:
    """Read the agent's text out of whatever shape the runtime returned."""
    body = response.json()
    if "choices" in body:
        return str(body["choices"][0]["message"]["content"])
    return str(body.get("output", ""))


def _user_text(client: ScriptedChatClient) -> str:
    """Everything the scripted model was given as user text."""
    return "\n".join(
        str(getattr(message, "text", ""))
        for exchange in client.received_messages
        for message in exchange
        if getattr(message, "role", "") == "user"
    )


class TestTheEndpointAnswers:
    """What works today, end to end, through the real routes."""

    def test_a_request_is_answered(self):
        app, client = build_service([says("I found two messages from John.")])

        with TestClient(app) as http:
            response = chat(http, "anything from John?")

        assert response.status_code == 200
        assert "two messages from John" in answer_of(response)
        assert client.stream_modes == [False]

    def test_the_agent_is_discoverable_as_a_model(self):
        """LibreChat lists it, and the description comes from `config/`."""
        app, _client = build_service([says("hello")])

        with TestClient(app) as http:
            body = http.get("/v1/models", headers={"x-api-key": API_KEY}).json()

        assert any(entry["id"] == AGENT_ID for entry in body["data"])

    def test_the_descriptor_advertises_what_this_service_accepts(self):
        """Discovery must describe the deployment, not an assumption about it.

        This harness authenticates with an API key and no token, so a descriptor
        naming a bearer scheme would send a caller to a door that is not there.
        The schemes are derived from the resolver the endpoints were configured
        with, which is why the two cannot disagree.
        """
        app, _client = build_service([says("hello")])

        descriptor = _only_descriptor(app)

        assert descriptor.security_schemes == ("apiKey",)

    def test_the_descriptor_admits_the_agent_invokes_tools(self):
        """It lists fifteen capabilities; claiming it invokes none contradicts that."""
        app, _client = build_service([says("hello")])

        descriptor = _only_descriptor(app)

        assert descriptor.skills
        assert descriptor.capabilities.tool_invocation

    def test_only_the_latest_turn_reaches_the_agent(self):
        """LibreChat re-sends the whole conversation; replaying it would duplicate."""
        app, client = build_service([says("first")])

        with TestClient(app) as http:
            http.post(
                "/v1/chat/completions",
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi"},
                        {"role": "user", "content": "what about John?"},
                    ],
                },
                headers={"x-api-key": API_KEY},
            )

        seen = _user_text(client)
        assert "what about John?" in seen
        assert "hello" not in seen
        assert client.stream_modes == [False]

    def test_streaming_request_returns_protocol_events_from_maf_updates(self):
        app, client = build_service([says("hello from a streamed response")])

        with TestClient(app) as http:
            response = chat(http, "hi", stream=True)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "hello" in response.text
        assert "response" in response.text
        assert client.stream_modes == [True]


@pytest.mark.security
class TestConversationConstructionFailuresAreVisible:
    """A failed first turn reaches the client and leaves safe, useful diagnostics."""

    @pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
    @pytest.mark.parametrize("failure", ["missing_secret", "backend_error"])
    def test_failed_stream_is_explicit_and_diagnostics_are_redacted(self, monkeypatch, caplog, protocol, failure):
        private_marker = "fixture-credential-never-to-be-logged"

        async def failing_build(*args, **kwargs):
            if failure == "missing_secret":
                load_configuration(ConfigurationDirectory(REPOSITORY_ROOT / "config"), "gmail-http", environment={})
            raise RuntimeError(f"Authorization: Bearer {private_marker}; retrieved private mail content")

        monkeypatch.setattr(MailConversationFactory, "build", failing_build)
        app = build_service_with_client(ScriptedChatClient([]), enable_responses=True)
        with TestClient(app) as http:
            if protocol == "responses":
                response = http.post(
                    "/v1/responses", json={"model": MODEL, "input": "hello", "stream": True},
                    headers={"x-api-key": API_KEY},
                )
            else:
                response = chat(http, "hello", stream=True)

        assert response.status_code == 200
        events = [
            json.loads(line.removeprefix("data:").strip())
            for line in response.text.splitlines()
            if line.startswith("data:") and line.removeprefix("data:").strip() != "[DONE]"
        ]
        if protocol == "responses":
            failed = [event for event in events if event.get("type") == "response.failed"]
            assert len(failed) == 1
            assert failed[0]["response"]["status"] == "failed"
            error = failed[0]["response"]["error"]
            sdk_errors = [event for event in events if event.get("type") == "error"]
            assert len(sdk_errors) == 1
            assert sdk_errors[0]["code"] == error["code"]
            assert sdk_errors[0]["message"] == error["message"]
            assert events.index(sdk_errors[0]) < events.index(failed[0])
            assert not any(event.get("type") == "response.completed" for event in events)
            transport = httpx.MockTransport(
                lambda request: httpx.Response(
                    200, content=response.content, headers={"content-type": "text/event-stream"},
                )
            )
            with (
                OpenAI(api_key=API_KEY, http_client=httpx.Client(transport=transport)) as sdk,
                sdk.responses.create(model=MODEL, input="hello", stream=True) as stream,
                pytest.raises(APIError, match="Agent stream execution failed"),
            ):
                list(stream)
        else:
            failed = [event for event in events if "error" in event]
            assert len(failed) == 1
            error = failed[0]["error"]
        assert error["code"] == "agent_execution_error"
        assert error["message"]
        assert private_marker not in response.text + caplog.text
        assert "retrieved private mail content" not in response.text + caplog.text
        assert "MCP_MAIL_OBO_CLIENT_SECRET" not in response.text
        if failure == "missing_secret":
            assert "MCP_MAIL_OBO_CLIENT_SECRET" in caplog.text
            assert "McpBindingError" in caplog.text
        else:
            assert "RuntimeError" in caplog.text


@pytest.mark.skipif(not maps_to_openai, reason=NOT_OPENAI_YET)
class TestOpenAiWireCompatibility:
    """The shape LibreChat actually needs.

    Skipped against a runtime that still answers with the exchange envelope, so
    the suite reports the gap instead of hiding it, and starts enforcing the
    contract the moment the mapping is available.
    """

    def test_the_body_is_a_chat_completion(self):
        app, _client = build_service([says("hello")])

        with TestClient(app) as http:
            body = chat(http, "hi").json()

        assert body["object"] == "chat.completion"

    def test_the_answer_sits_in_a_choice(self):
        app, _client = build_service([says("hello there")])

        with TestClient(app) as http:
            body = chat(http, "hi").json()

        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["message"]["content"] == "hello there"


@pytest.mark.skipif(not forwards_the_conversation, reason=NO_HEADER_FORWARDING)
class TestEachDiscussionGetsItsOwnSession:
    """LibreChat opens a discussion per conversation; the agent must follow.

    Sharing one session across discussions would let a confirmation raised in one
    be answered from another, and would carry mail read in one into the context
    of the next.
    """

    def test_two_conversations_do_not_share_a_session(self):
        app, _client = build_service([says("first"), says("second")])

        with TestClient(app) as http:
            chat(http, "anything from John?", conversation="conv-a")
            chat(http, "anything from Mary?", conversation="conv-b")

        assert app.state.conversations.live_conversations == 2

    def test_the_same_conversation_is_continued(self):
        app, _client = build_service([says("first"), says("second")])

        with TestClient(app) as http:
            chat(http, "anything from John?", conversation="conv-a")
            chat(http, "and after that?", conversation="conv-a")

        assert app.state.conversations.live_conversations == 1

    def test_a_confirmation_cannot_be_answered_from_another_conversation(self):
        """A ticket belongs to one conversation, and a discussion is one."""
        app, _client = build_service(
            [
                calls(ToolCall(MailToolName.APPLY_LABEL.value, {"message_id": MESSAGE_ID, "label_id": LABEL_ID})),
                says("I have asked for confirmation."),
                says("nothing pending here"),
            ]
        )

        with TestClient(app) as http:
            raised = answer_of(chat(http, "file it under Finance", conversation="conv-a"))
            ticket = ticket_in(raised)
            elsewhere = answer_of(chat(http, f"CONFIRM {ticket}", conversation="conv-b"))

        assert "not awaiting an answer" in elsewhere


@pytest.mark.security
class TestAnUnauthenticatedCallerIsRefused:
    """Without a subject there is nothing to partition state by."""

    def test_a_request_without_a_key_is_rejected(self):
        app, _client = build_service([says("hello")])

        with TestClient(app) as http:
            response = chat(http, "anything from John?", key=None)

        assert response.status_code in (401, 403)

    def test_a_wrong_key_is_rejected(self):
        app, _client = build_service([says("hello")])

        with TestClient(app) as http:
            response = chat(http, "anything from John?", key="not-the-key")

        assert response.status_code in (401, 403)

    def test_the_model_is_never_reached_without_authentication(self):
        """Refusing after asking a model would still have spent money and data."""
        app, client = build_service([says("hello")])

        with TestClient(app) as http:
            chat(http, "anything from John?", key=None)

        assert client.turn == 0

    def test_discovery_is_not_public(self):
        """Listing the agent lists every capability it has.

        Discovery carries its own authentication flag in the runtime, and it
        defaults to open. Left that way, an unauthenticated caller reads a map of
        what this mailbox can be made to do - including which operations write.
        """
        app, _client = build_service([says("hello")])

        with TestClient(app) as http:
            response = http.get("/v1/models")

        assert response.status_code in (401, 403)


@pytest.mark.security
class TestAGatedOperationIsDeferredOverHttp:
    """A request must be answered, so an approval cannot hold the connection."""

    def test_the_reply_asks_for_a_confirmation(self):
        app, _client = build_service(
            [
                calls(ToolCall(MailToolName.APPLY_LABEL.value, {"message_id": MESSAGE_ID, "label_id": LABEL_ID})),
                says("I have asked for confirmation."),
            ]
        )

        with TestClient(app) as http:
            first = answer_of(chat(http, "file the Project Alpha message under Finance"))

        assert "CONFIRM cfm-" in first
        assert "nothing has been changed yet" in first

    def test_confirming_in_a_second_request_performs_it(self):
        app, _client = build_service(
            [
                calls(ToolCall(MailToolName.APPLY_LABEL.value, {"message_id": MESSAGE_ID, "label_id": LABEL_ID})),
                says("I have asked for confirmation."),
            ]
        )

        with TestClient(app) as http:
            first = answer_of(chat(http, "file the Project Alpha message under Finance"))
            ticket = ticket_in(first)

            second = answer_of(chat(http, f"CONFIRM {ticket}"))

        assert MailToolName.APPLY_LABEL.value in second
