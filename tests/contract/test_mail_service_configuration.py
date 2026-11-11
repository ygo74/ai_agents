"""The Mail Agent HTTP service refuses to run without a caller.

These drive the **real** ``build_app`` - the one a deployment runs - rather than
a harness, because what is under test is the wiring itself.

The guard exists because of what the descriptor work uncovered. The Mail Agent
had no equivalent of the Wiki Agent's start-up refusal, and the gap was invisible
while discovery asserted ``("jwt", "oidc")`` whether or not either was
configured. Deriving the descriptor from the authentication actually in force
turned a service that quietly served open into one that will not start.

A mailbox makes the stakes plain: an unauthenticated service has no subject to
partition state by and no address to serve, so it would hand the configured
mailbox to whoever asked first.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
import yaml
from tests.support.maf_fakes import ScriptedChatClient, says
from tests.support.mcp_http import connected_mcp_session, invoke_agent
from ygo74.agent_runtime.domains.configuration.directory import CONFIG_DIR_VARIABLE

from ai_agent_lab.mail.bootstrap.factory import MailAgentApplicationFactory
from ai_agent_lab.mail.bootstrap.service import (
    MailServiceConfigurationError,
    build_app,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
JWT_SIGNING_KEY = "mail-agent-contract-test-signing-key"
JWT_ISSUER = "https://identity.example.test/agents"
JWT_AUDIENCE = "mail-agent-contract-test"

pytestmark = pytest.mark.security


@pytest.fixture(autouse=True)
def single_caller_deployment(monkeypatch, tmp_path):
    """Create an isolated API-key deployment independent of the delivered JWT manifest."""
    monkeypatch.setenv("MAIL_AGENT_MODE", "mock")
    monkeypatch.setenv("MAIL_AGENT_USER_ID", "local-user")
    monkeypatch.setenv("MAIL_AGENT_USER_EMAIL", "local-user@example.com")
    monkeypatch.setenv("MAIL_AGENT_HTTP_API_KEY", "demonstration-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-service-wiring-tests")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("MAIL_AGENT_HTTP_OIDC_ISSUER", raising=False)

    config_root = tmp_path / "config"
    shutil.copytree(REPOSITORY_ROOT / "config", config_root)
    manifest_path = config_root / "agents" / "mail" / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["http"]["security"] = {
        "mode": "api_key",
        "api_key": {
            "value": "${MAIL_AGENT_HTTP_API_KEY}",
            "header_name": "X-API-Key",
            "user": {"subject": "local-user", "email": "local-user@example.com"},
        },
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_VARIABLE, str(config_root))

    env_file = tmp_path / "mail-agent.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("MAIL_AGENT_ENV_FILE", str(env_file))


class TestTheServiceRefusesToRunOpen:
    """Failing to start is the correct outcome, and the message has to say why."""

    def test_it_starts_when_a_caller_can_be_identified(self):
        app = build_app(base_path=REPOSITORY_ROOT)

        assert app.state.conversations is not None

    def test_it_will_not_start_without_a_way_to_identify_a_caller(self, monkeypatch):
        monkeypatch.setenv("MAIL_AGENT_HTTP_API_KEY", "")

        with pytest.raises(
            MailServiceConfigurationError,
            match=r"http\.security\.api_key\.value",
        ):
            build_app(base_path=REPOSITORY_ROOT)

    async def test_manifest_selects_the_api_key_and_exposes_declared_routes(self):
        """The manifest owns Mail's selected routes and API-key policy."""
        app = build_app(base_path=REPOSITORY_ROOT)

        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as http,
        ):
            no_credential = await http.get("/v1/models")
            api_key = await http.get(
                "/v1/models",
                headers={"x-api-key": "demonstration-key"},
            )
            disabled_messages = await http.post("/v1/messages", json={})
            async with connected_mcp_session(
                app,
                {"x-api-key": "demonstration-key"},
            ) as mcp:
                tools = await mcp.list_tools()

        assert no_credential.status_code in (401, 403)
        assert api_key.status_code == 200
        assert disabled_messages.status_code == 404
        assert [tool.name for tool in tools.tools] == ["invoke_agent"]


def _configure_static_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a local signer to exercise caller-scoped MCP conversations."""
    configuration_root = Path(os.environ[CONFIG_DIR_VARIABLE])
    manifest_path = configuration_root / "agents" / "mail" / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["http"]["mcp"] = {"resource_url": "${MAIL_AGENT_HTTP_MCP_RESOURCE_URL}"}
    manifest["http"]["security"] = {
        "mode": "jwt",
        "jwt": {
            "issuer": JWT_ISSUER,
            "audience": JWT_AUDIENCE,
            "secret": "${MAIL_AGENT_HTTP_JWT_SECRET}",
            "allowed_algorithms": ["HS256"],
        },
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("MAIL_AGENT_HTTP_JWT_SECRET", JWT_SIGNING_KEY)
    monkeypatch.setenv(
        "MAIL_AGENT_HTTP_MCP_RESOURCE_URL",
        "https://mail.example.test/mcp",
    )


def _access_token(subject: str, *, email: str | None) -> str:
    """Sign a short-lived test token for the local static-JWT policy."""
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
    }
    if email is not None:
        claims["email"] = email
    return jwt.encode(claims, JWT_SIGNING_KEY, algorithm="HS256")


@pytest.mark.security
async def test_mcp_requires_mail_email_and_partitions_same_conversation_by_subject(monkeypatch):
    """MCP uses verified caller identity for both Mail's email rule and cache key."""
    _configure_static_jwt(monkeypatch)
    model = ScriptedChatClient([says("first mailbox answer"), says("second mailbox answer")])
    monkeypatch.setattr(MailAgentApplicationFactory, "build_chat_client", lambda self: model)
    app = build_app(base_path=REPOSITORY_ROOT)

    async with app.router.lifespan_context(app):
        async with connected_mcp_session(
            app,
            {"authorization": f"Bearer {_access_token('mail-user-no-email', email=None)}"},
        ) as session:
            missing_email = await invoke_agent(session, "do not reach the model")

        assert missing_email.isError is True
        assert model.received_messages == []

        async with connected_mcp_session(
            app,
            {"authorization": f"Bearer {_access_token('mail-user-one', email='one@example.test')}"},
        ) as first_session:
            first = await invoke_agent(
                first_session,
                "private mailbox phrase for user one",
                conversation_id="same-thread",
            )

        async with connected_mcp_session(
            app,
            {"authorization": f"Bearer {_access_token('mail-user-two', email='two@example.test')}"},
        ) as second_session:
            second = await invoke_agent(
                second_session,
                "private mailbox phrase for user two",
                conversation_id="same-thread",
            )

        assert first.isError is False
        assert second.isError is False
        assert first.structuredContent["conversation_id"] == "same-thread"
        assert second.structuredContent["conversation_id"] == "same-thread"
        assert app.state.conversations.live_conversations == 2

    second_prompt = "\n".join(str(message) for message in model.received_messages[1])
    assert "private mailbox phrase for user one" not in second_prompt
