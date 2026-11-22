"""Exercise the Credit HTTP host through real runtime routes and native MAF."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
import yaml
from fastapi.testclient import TestClient
from openai import OpenAI
from tests.support.maf_fakes import ScriptedChatClient, ToolCall, calls, says
from tests.unit.credit.test_identification import FakeEdgar, company

from ai_agent_lab.credit.adapters.capabilities.registry import build_registry
from ai_agent_lab.credit.application.skills.identification import IdentificationSkill
from ai_agent_lab.credit.bootstrap.composition import CreditApplication
from ai_agent_lab.credit.bootstrap.service import build_app

MODEL = "corporate-credit-analyst"
KEY = "fixture-credit-http-key"


def service(monkeypatch, script, config=Path("config")):
    """Replace external dependencies while retaining authentication and tool gates."""
    monkeypatch.setenv("CREDIT_AGENT_HTTP_API_KEY", KEY)
    model = ScriptedChatClient(script)
    fake = FakeEdgar([company(tickers=("AAPL",))])
    applications = []
    closed = []

    def application_factory(user):
        application = CreditApplication(config, user=user, load_environment=False)
        application.registry = build_registry(application.manifest, IdentificationSkill(fake))
        original_close = application.aclose

        async def close():
            closed.append(user)
            await original_close()

        application.aclose = close
        applications.append(application)
        return application

    app = build_app(config=config, client=model, application_factory=application_factory)
    return app, model, fake, applications, closed


@pytest.mark.parametrize("protocol", ["chat/completions", "responses"])
@pytest.mark.parametrize("stream", [False, True])
def test_client_invokes_identification_and_resources_close(monkeypatch, protocol, stream):
    app, model, fake, applications, closed = service(monkeypatch, [
        calls(ToolCall("identify_company", {"query": "aapl", "query_type": "ticker"})),
        says("Apple Inc., CIK 0000320193, identified for analyst review."),
    ])
    payload = {"model": MODEL, "stream": stream}
    if protocol == "responses":
        payload["input"] = "Identify AAPL"
    else:
        payload["messages"] = [{"role": "user", "content": "Identify AAPL"}]
    with TestClient(app) as http:
        response = http.post(f"/v1/{protocol}", json=payload, headers={"X-API-Key": KEY})
        assert response.status_code == 200, response.text
        assert "0000320193" in response.text
        if stream:
            assert response.headers["content-type"].startswith("text/event-stream")
        else:
            assert response.json()["object"] == ("response" if protocol == "responses" else "chat.completion")
    assert fake.calls == [("search", "AAPL"), ("profile", "0000320193")]
    assert set(model.offered_tools[0]) == {"identify_company"}
    assert applications[0].user.user_id == "local-analyst"
    assert len(closed) == 1


@pytest.mark.parametrize("key", [None, "wrong-key"])
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses", "/v1/models"])
def test_authentication_precedes_conversation_construction(monkeypatch, key, path):
    app, model, fake, applications, _ = service(monkeypatch, [says("hello")])
    with TestClient(app) as http:
        headers = {"X-API-Key": key} if key else {}
        if path == "/v1/models":
            response = http.get(path, headers=headers)
        else:
            response = http.post(path, headers=headers, json={
                "model": MODEL, "input": "Identify AAPL",
                "messages": [{"role": "user", "content": "Identify AAPL"}],
            })
    assert response.status_code in (401, 403)
    assert not applications
    assert not fake.calls
    assert model.turn == 0


def test_openai_sdk_discovery_and_conversation_continuity(monkeypatch):
    app, model, _, applications, closed = service(monkeypatch, [says("first"), says("second"), says("third")])
    with TestClient(app) as http:
        with OpenAI(base_url="http://testserver/v1", api_key="unused", http_client=http,
                    default_headers={"X-API-Key": KEY}) as sdk:
            assert MODEL in [entry.id for entry in sdk.models.list().data]
            for conversation in ("a", "a", "b"):
                result = sdk.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "hello"}],
                                                     extra_headers={"X-Conversation-Id": conversation})
                assert result.choices[0].message.content
        assert len(applications) == 2
        assert [application.user.session_id for application in applications] == ["a", "b"]
        assert any(message.text == "first" for message in model.received_messages[1])
        assert not any(message.text == "first" for message in model.received_messages[2])
    assert len(closed) == 2


def test_missing_key_refuses_startup(monkeypatch):
    monkeypatch.delenv("CREDIT_AGENT_HTTP_API_KEY", raising=False)
    with pytest.raises(ValueError):
        build_app(config=Path("config"))


def test_verified_jwt_subjects_partition_the_same_conversation(monkeypatch, tmp_path):
    """Two callers using the same routing handle must have separate history and tools."""
    config = tmp_path / "config"
    shutil.copytree("config", config)
    manifest_path = config / "agents/credit/agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["http"]["security"] = {"mode": "jwt", "jwt": {
        "issuer": "https://issuer.example.test", "audience": MODEL,
        "secret": "${CREDIT_TEST_JWT_SECRET}", "allowed_algorithms": ["HS256"],
        "required_claims": ["sub", "exp", "iss", "aud"],
    }}
    manifest_path.write_text(yaml.safe_dump(manifest))
    signing_material = "test-signing-material-at-least-thirty-two-bytes"
    monkeypatch.setenv("CREDIT_TEST_JWT_SECRET", signing_material)
    app, model, _, applications, closed = service(monkeypatch, [says("alice-only"), says("bob-only")], config)
    with TestClient(app) as http:
        for subject in ("alice", "bob"):
            token = jwt.encode({"sub": subject, "iss": "https://issuer.example.test", "aud": MODEL,
                                "exp": datetime.now(UTC) + timedelta(minutes=5)}, signing_material, algorithm="HS256")
            response = http.post("/v1/chat/completions", headers={
                "Authorization": f"Bearer {token}", "X-Conversation-Id": "shared",
            }, json={"model": MODEL, "messages": [{"role": "user", "content": "Identify AAPL"}],
                     "user": "spoofed", "auth_context": {"identity": {"subject": "spoofed"}}})
            assert response.status_code == 200, response.text
        assert http.get("/v1/models", headers={"X-API-Key": KEY}).status_code in (401, 403)
    assert [application.user.user_id for application in applications] == ["alice", "bob"]
    assert all(application.user.session_id == "shared" for application in applications)
    assert not any(message.text == "alice-only" for message in model.received_messages[1])
    assert len(closed) == 2


def test_failed_native_construction_closes_resources(monkeypatch):
    """A failed factory cannot leave an orphan MCP scope or disclose its exception."""
    app, _, _, applications, closed = service(monkeypatch, [])

    def fail(*args, **kwargs):
        raise RuntimeError("fixture-private-model-credential")

    monkeypatch.setattr(CreditApplication, "native_agent", fail)
    with TestClient(app) as http:
        response = http.post("/v1/responses", headers={"X-API-Key": KEY},
                             json={"model": MODEL, "input": "Identify AAPL", "stream": True})
        assert response.status_code == 200
        assert "response.failed" in response.text
        assert "fixture-private-model-credential" not in response.text
    assert len(applications) == len(closed) == 1
