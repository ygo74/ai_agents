"""Both HTTP services share one runtime-owned OIDC client lifecycle."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from tests.support.langgraph_fakes import ScriptedChatModel
from ygo74.agent_runtime.domains.configuration.directory import CONFIG_DIR_VARIABLE

from ai_agent_lab.mail.bootstrap import service as mail_service
from ai_agent_lab.wiki.bootstrap import service as wiki_service

ROOT = Path(__file__).resolve().parents[2]
ISSUER = "https://issuer.example.test"


@pytest.mark.parametrize("service", ["mail", "wiki"])
@pytest.mark.parametrize("explicit_jwks", [False, True])
async def test_oidc_http_client_is_lazy_shared_and_closed(monkeypatch, service, explicit_jwks, tmp_path):
    """The manifest-selected resolver lazily shares and closes its HTTP client."""
    service_prefix = f"{service.upper()}_AGENT_"
    monkeypatch.setenv(f"{service_prefix}MODE", "mock")
    monkeypatch.setenv(f"{service_prefix}HTTP_API_KEY", "must-not-be-used")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    config_root = tmp_path / "config"
    shutil.copytree(ROOT / "config", config_root)
    manifest_path = config_root / "agents" / service / "agent.yaml"
    document = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    jwt_settings = {
        "allowed_algorithms": ["RS256"],
        "required_claims": ["sub", "exp", "iss", "aud"],
        "issuer": ISSUER,
        "audience": "test-agent",
        "roles_claim_path": "realm_access.roles",
    }
    if explicit_jwks:
        jwt_settings["jwks_url"] = f"{ISSUER}/keys"
    document["http"]["security"] = {"mode": "jwt", "jwt": jwt_settings}
    manifest_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_VARIABLE, str(config_root))

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
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as http:
        assert not clients
        assert not requests
        for _ in range(2):
            response = await http.get(
                "/v1/models",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200, response.text
            assert len(clients) == 1
            assert not clients[0].is_closed
        api_key_response = await http.get(
            "/v1/models", headers={"x-api-key": "must-not-be-used"}
        )
        assert api_key_response.status_code in (401, 403)
        assert len(clients) == 1
        assert requests == (
            ["/keys"]
            if explicit_jwks
            else ["/.well-known/openid-configuration", "/keys"]
        )
    assert clients[0].is_closed
