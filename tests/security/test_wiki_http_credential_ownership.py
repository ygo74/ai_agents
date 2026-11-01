"""A second JWT subject must not inherit the fixed/legacy Wiki credentials over HTTP.

CR-001 bound the deployment's fixed ``WIKI_MCP_USER_ACCOUNT``/``WIKI_MCP_USER_SECRET``
to their configured owner (``WIKI_AGENT_USER_ID``) inside ``WikiToolsProvider``, and
``tests/security/test_wiki_credential_ownership.py`` already proves that at the
provider level. This module proves the same guarantee end to end, through the real
``wiki_service.build_app`` a deployment actually runs: two distinct JWT-authenticated
callers hit the same running service, and only the owner's read succeeds. The
second caller is refused rather than silently served with the owner's credentials.

No live MCP is reached: ``AtlassianWikiTools._call`` is mocked, and
``McpConnection._connect`` is monkeypatched to raise if ever awaited. The manifest's
``http.security`` is rewritten to JWT only so this test can mint two distinct
subjects over HTTP; the deployment's own explicit JWT configuration (issuer, JWKS,
required claims) remains entirely runtime-owned and unedited here.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from tests.support.langgraph_fakes import ScriptedChatModel, ScriptedTurn, ToolCall, calls, says
from tests.unit.wiki.test_atlassian_dialect import PAGE
from ygo74.agent_runtime.domains.configuration.directory import CONFIG_DIR_VARIABLE
from ygo74.agent_runtime.domains.mcp.binding import McpConnection

from ai_agent_lab.wiki.application.skills.analysis import PageSummaryOutput
from ai_agent_lab.wiki.bootstrap import service as wiki_service
from ai_agent_lab.wiki.bootstrap.composition import WikiAgentCompositionRoot
from ai_agent_lab.wiki.infrastructure.mcp.atlassian.client import AtlassianWikiTools

ROOT = Path(__file__).resolve().parents[2]
ISSUER = "https://issuer.example.test"
AUDIENCE = "wiki-agent"
OWNER_SUBJECT = "diana"
OTHER_SUBJECT = "alice"
PAGE_ID = "apollo-architecture"

pytestmark = pytest.mark.security


def _mint(subject: str, private_key: rsa.RSAPrivateKey, kid: str) -> str:
    """Encode one RS256 access token for the given subject."""
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _read_script(tool_name: str) -> list[ScriptedTurn]:
    """Fetch or summarise the owner's page, then report."""
    return [
        calls(ToolCall(tool_name, {"page_id": PAGE_ID})),
        says("Page delivered."),
    ]


def _answer_of(response: httpx.Response) -> str:
    """Read the agent's text out of whatever shape the runtime returned."""
    body = response.json()
    if "choices" in body:
        return str(body["choices"][0]["message"]["content"])
    return str(body.get("output", ""))


@pytest.fixture
def jwt_wiki_deployment(monkeypatch, tmp_path):
    """Stand up the real Wiki HTTP service with JWT security and legacy MCP credentials.

    Two subjects will later authenticate against the one running app: the
    configured owner (``WIKI_AGENT_USER_ID=diana``) and an unrelated caller
    (``alice``). No live MCP connection is made; ``AtlassianWikiTools._call`` is
    mocked to answer like the real server would.
    """
    monkeypatch.setenv("WIKI_AGENT_MODE", "mcp")
    monkeypatch.setenv("WIKI_AGENT_USER_ID", OWNER_SUBJECT)
    monkeypatch.setenv("WIKI_MCP_AUTH_SCHEME", "token")
    monkeypatch.setenv("WIKI_MCP_USER_ACCOUNT", "diana@example.com")
    monkeypatch.setenv("WIKI_MCP_USER_SECRET", "owner-fixture-token")
    monkeypatch.setenv("WIKI_MCP_READ_ONLY", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("WIKI_AGENT_HTTP_API_KEY", raising=False)

    config_root = tmp_path / "config"
    shutil.copytree(ROOT / "config", config_root)
    manifest_path = config_root / "agents" / "wiki" / "agent.yaml"
    document = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    # Only the authentication *mode* changes, to mint two distinct subjects over
    # HTTP; explicit JWT posture (issuer, JWKS, claims) is exactly what the
    # runtime already owns and validates, unedited beyond selecting it here.
    document["http"]["security"] = {
        "mode": "jwt",
        "jwt": {
            "allowed_algorithms": ["RS256"],
            "required_claims": ["sub", "exp", "iss", "aud"],
            "issuer": ISSUER,
            "audience": AUDIENCE,
            "jwks_url": f"{ISSUER}/keys",
        },
    }
    # The legacy header-credential scenario applies to the HTTP MCP binding; the
    # bound server itself still answers through the mocked dialect below.
    document["mcp_server"] = "mcp-atlassian-http"
    manifest_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_VARIABLE, str(config_root))

    read = AsyncMock(return_value={"metadata": PAGE})
    connect = AsyncMock(side_effect=AssertionError("security tests must not connect to MCP"))
    monkeypatch.setattr(AtlassianWikiTools, "_call", read)
    monkeypatch.setattr(McpConnection, "_connect", connect)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update(kid="test-key", use="sig", alg="RS256")

    client_type = httpx.Client

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/keys"
        return httpx.Response(200, json={"keys": [public_jwk]})

    def create_client(**kwargs):
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "Client", create_client)

    owner_token = _mint(OWNER_SUBJECT, private_key, "test-key")
    other_token = _mint(OTHER_SUBJECT, private_key, "test-key")
    return owner_token, other_token, read, connect


@pytest.mark.parametrize("tool_name", ["get_page", "summarise_page"])
async def test_a_second_subject_is_rejected_rather_than_served_the_owners_fixed_credentials(
    jwt_wiki_deployment, monkeypatch, tool_name,
):
    """The owner succeeds; a distinct caller receives 403 before retrieval or reasoning."""
    owner_token, other_token, read, connect = jwt_wiki_deployment
    reasoner = Mock(reason=AsyncMock(return_value=PageSummaryOutput(summary="Owner summary")))
    monkeypatch.setattr(WikiAgentCompositionRoot, "_reasoner", lambda _: reasoner)
    app = wiki_service.build_app(base_path=ROOT, chat_model=ScriptedChatModel(_read_script(tool_name)))

    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        owner_response = await http.post(
            "/v1/chat/completions",
            json={
                "model": wiki_service.AGENT_ID,
                "messages": [{"role": "user", "content": f"show me {PAGE_ID}"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200, owner_response.text
        assert "Page delivered" in _answer_of(owner_response)

        other_response = await http.post(
            "/v1/chat/completions",
            json={
                "model": wiki_service.AGENT_ID,
                "messages": [{"role": "user", "content": f"show me {PAGE_ID}"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {other_token}"},
        )

    # Composition eagerly builds every skill for a new principal, so the owner
    # guard rejects this caller before any tool call is attempted: the request
    # fails outright rather than quietly succeeding with the owner's identity.
    assert other_response.status_code == 403, other_response.text
    refusal = other_response.text
    assert "Page delivered" not in refusal
    assert "owner-fixture-token" not in refusal
    assert "diana@example.com" not in refusal

    connect.assert_not_awaited()
    assert read.await_count == 1
    assert reasoner.reason.await_count == (1 if tool_name == "summarise_page" else 0)
