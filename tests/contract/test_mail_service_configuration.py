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

    def test_an_issuer_alone_is_refused_while_the_token_path_is_disabled(self, monkeypatch):
        """The trap this guard was written for.

        Setting an issuer looks like configuring authentication. With the JWT
        wiring switched off it authenticates nobody, and the previous behaviour
        was to start anyway and accept every request.
        """
        monkeypatch.setenv("MAIL_AGENT_HTTP_API_KEY", "")
        monkeypatch.setenv("MAIL_AGENT_HTTP_OIDC_ISSUER", "https://realm.example/auth")

        with pytest.raises(MailServiceConfigurationError, match="JWT path"):
            build_app(base_path=REPOSITORY_ROOT)
