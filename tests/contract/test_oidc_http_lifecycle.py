"""Both HTTP services share one application-owned OIDC pool."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from tests.support.langgraph_fakes import ScriptedChatModel
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest

from ai_agent_lab.mail.bootstrap import service as mail_service
from ai_agent_lab.wiki.bootstrap import service as wiki_service

ROOT = Path(__file__).resolve().parents[2]
ISSUER = "https://issuer.example.test"


@pytest.mark.parametrize("service", ["mail", "wiki"])
@pytest.mark.parametrize("explicit_jwks", [False, True])
def test_oidc_pool_is_started_shared_and_closed(monkeypatch, service, explicit_jwks):
    prefix = f"{service.upper()}_AGENT_"
    monkeypatch.setenv(f"{prefix}MODE", "mock")
    monkeypatch.setenv(f"{prefix}HTTP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv(f"{prefix}HTTP_OIDC_AUDIENCE", "test-agent")
    monkeypatch.setenv(f"{prefix}HTTP_JWKS_URL", f"{ISSUER}/keys" if explicit_jwks else "")
    monkeypatch.delenv(f"{prefix}HTTP_JWKS_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    if service == "wiki":
        monkeypatch.setattr(
            wiki_service.WikiAgentCompositionRoot,
            "manifest",
            lambda self: AgentManifest(
                name="wiki-agent",
                description="HTTP lifecycle test",
                instructions="Test HTTP authentication.",
                skills=(),
            ),
        )

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update(kid="test-key", use="sig", alg="RS256")
    token = jwt.encode(
        {
            "sub": "test-user",
            "iss": ISSUER,
            "aud": "test-agent",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    requests: list[str] = []
    clients: list[httpx.Client] = []
    client_type = httpx.Client

    def respond(request):
        requests.append(request.url.path)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"jwks_uri": f"{ISSUER}/keys"})
        assert request.url.path == "/keys"
        return httpx.Response(200, json={"keys": [public_jwk]})

    def create_client(**kwargs):
        client = client_type(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", create_client)
    app = (
        mail_service.build_app(base_path=ROOT)
        if service == "mail"
        else wiki_service.build_app(base_path=ROOT, chat_model=ScriptedChatModel([]))
    )
    assert not clients
    assert not requests
    with TestClient(app) as http:
        assert len(clients) == 1
        assert not clients[0].is_closed
        assert not requests
        for _ in range(2):
            response = http.get("/v1/models", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, response.text
        assert len(clients) == 1
        assert requests == (
            ["/keys"] if explicit_jwks else ["/.well-known/openid-configuration", "/keys"]
        )
    assert clients[0].is_closed
