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

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.support.maf_fakes import ScriptedChatClient, ToolCall, calls, says
from ygo74.agent_runtime import (
    AdvertisedSecurity,
    AgentDescriptor,
    DescriptorRegistry,
    DiscoveryConfiguration,
    ResolvedUser,
    StaticApiKeyUserResolver,
    add_ai_endpoints,
)

from ai_agent_lab.core.serving.runtimes import ConversationRuntimeCache
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.application.entrypoints.conversation import (
    MailConversation,
    MailConversationEngine,
    MailConversationFactory,
)
from ai_agent_lab.mail.application.entrypoints.http import (
    MailAgentDescriptorFactory,
    MailAgentEntrypoint,
)
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner

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
    from ygo74.agent_runtime.domains.mapping.response_mapper import map_response

    rendered = map_response(
        "openai.chat_completions",
        {"request_id": "probe", "status": "success", "output": "ok"},
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
    composition = MailAgentCompositionRoot(
        MailAgentSettings(always_confirm_tools=MailToolName.APPLY_LABEL.value),
        client,
        reasoner=ScriptedTextReasoner({}),
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
        enable_openai_responses=False,
        require_bearer_token=True,
        api_key_resolver=api_key_resolver,
        descriptor_registry=DescriptorRegistry([descriptor]),
        discovery=DiscoveryConfiguration(enable_openai_models=True, require_authentication=True),
    )
    return app, client


def _only_descriptor(app: FastAPI) -> AgentDescriptor:
    """Return the descriptor this harness registered.

    Read from the object the harness built rather than from the discovery
    payload: the projection onto the OpenAI model shape drops the security
    schemes, and those are exactly what these tests are about.
    """
    descriptor = app.state.descriptor
    assert isinstance(descriptor, AgentDescriptor)
    return descriptor


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
        app, _client = build_service([says("I found two messages from John.")])

        with TestClient(app) as http:
            response = chat(http, "anything from John?")

        assert response.status_code == 200
        assert "two messages from John" in answer_of(response)

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
