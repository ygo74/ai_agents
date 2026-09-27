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

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_agent_lab.mail.application.entrypoints.service import (
    MailServiceConfigurationError,
    build_app,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.security


@pytest.fixture(autouse=True)
def single_caller_deployment(monkeypatch):
    """Configure the single-caller posture the module is written against."""
    monkeypatch.setenv("MAIL_AGENT_MODE", "mock")
    monkeypatch.setenv("MAIL_AGENT_USER_ID", "local-user")
    monkeypatch.setenv("MAIL_AGENT_USER_EMAIL", "local-user@example.com")
    monkeypatch.setenv("MAIL_AGENT_HTTP_API_KEY", "demonstration-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-service-wiring-tests")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("MAIL_AGENT_HTTP_OIDC_ISSUER", raising=False)


class TestTheServiceRefusesToRunOpen:
    """Failing to start is the correct outcome, and the message has to say why."""

    def test_it_starts_when_a_caller_can_be_identified(self):
        app = build_app(base_path=REPOSITORY_ROOT)

        assert app.state.conversations is not None

    def test_it_will_not_start_without_a_way_to_identify_a_caller(self, monkeypatch):
        monkeypatch.setenv("MAIL_AGENT_HTTP_API_KEY", "")

        with pytest.raises(MailServiceConfigurationError, match="needs a caller"):
            build_app(base_path=REPOSITORY_ROOT)

    def test_an_issuer_alone_enables_oidc(self, monkeypatch):
        """OIDC is a supported caller identity, not an open-service setting."""
        monkeypatch.setenv("MAIL_AGENT_HTTP_API_KEY", "")
        monkeypatch.setenv("MAIL_AGENT_HTTP_OIDC_ISSUER", "https://realm.example/auth")
        monkeypatch.setenv(
            "MAIL_AGENT_HTTP_JWKS_URL",
            "https://realm.example/auth/protocol/openid-connect/certs",
        )

        app = build_app(base_path=REPOSITORY_ROOT)

        assert app.state.conversations is not None

    def test_oidc_takes_precedence_over_the_configured_api_key(self, monkeypatch):
        """An old demo key must not remain a second way into an OIDC service."""
        monkeypatch.setenv("MAIL_AGENT_HTTP_OIDC_ISSUER", "https://realm.example/auth")
        monkeypatch.setenv(
            "MAIL_AGENT_HTTP_JWKS_URL",
            "https://realm.example/auth/protocol/openid-connect/certs",
        )

        app = build_app(base_path=REPOSITORY_ROOT)

        with TestClient(app) as http:
            no_credential = http.get("/v1/models")
            api_key = http.get("/v1/models", headers={"x-api-key": "demonstration-key"})

        assert no_credential.status_code in (401, 403)
        assert api_key.status_code in (401, 403)

    def test_it_will_not_start_when_oidc_and_api_key_are_both_absent(self, monkeypatch):
        monkeypatch.setenv("MAIL_AGENT_HTTP_API_KEY", "")
        monkeypatch.delenv("MAIL_AGENT_HTTP_OIDC_ISSUER", raising=False)

        with pytest.raises(MailServiceConfigurationError, match="needs a caller"):
            build_app(base_path=REPOSITORY_ROOT)
