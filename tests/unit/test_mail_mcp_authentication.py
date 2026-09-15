"""Tests of how the Mail Agent proves itself to an MCP server over HTTP.

Two servers can sit behind an HTTP binding, and they need different things.
Google's endpoint wants the authorisation-code flow; the server this repository
deploys next to the agent wants the shared secret the two were given. Guessing
between them is not possible, so the deployment says which - and saying nothing
keeps the behaviour every existing deployment already had.
"""

from __future__ import annotations

import pytest

from ai_agent_lab.mail.config.settings import MailMcpAuthScheme, MailMcpSettings
from ai_agent_lab.mail.mail_errors import MailAgentConfigurationError
from ai_agent_lab.mail.mcp.bearer import BearerTokenAuth

SECRET = "a-shared-deployment-secret"  # noqa: S105 - a fixture, not a credential


class TestTheSchemeIsChosenByConfiguration:
    """Never inferred from the URL: two servers can share a shape."""

    def test_oauth_is_the_default(self):
        """Before this setting existed, an HTTP binding always meant Google."""
        assert MailMcpSettings(_env_file=None).auth_scheme is MailMcpAuthScheme.OAUTH

    def test_bearer_is_selected_explicitly(self):
        settings = MailMcpSettings(_env_file=None, auth_scheme="bearer", http_token=SECRET)

        assert settings.auth_scheme is MailMcpAuthScheme.BEARER
        assert settings.bearer_token() == SECRET


@pytest.mark.security
class TestABearerDeploymentNeedsASecret:
    """Half-configured is refused, because the symptom would appear late."""

    def test_a_missing_secret_is_refused_with_an_actionable_message(self):
        settings = MailMcpSettings(_env_file=None, auth_scheme="bearer")

        with pytest.raises(MailAgentConfigurationError) as refusal:
            settings.bearer_token()

        assert "MAIL_MCP_HTTP_TOKEN" in str(refusal.value)

    def test_a_blank_secret_is_not_a_secret(self):
        blank = "   "
        settings = MailMcpSettings(_env_file=None, auth_scheme="bearer", http_token=blank)

        with pytest.raises(MailAgentConfigurationError):
            settings.bearer_token()


@pytest.mark.security
class TestTheSecretStaysOutOfSight:
    """A shared secret in a log is a shared secret in an incident report."""

    def test_the_settings_never_print_it(self):
        settings = MailMcpSettings(_env_file=None, auth_scheme="bearer", http_token=SECRET)

        assert SECRET not in repr(settings)
        assert SECRET not in str(settings)

    def test_the_credential_never_prints_it(self):
        auth = BearerTokenAuth(SECRET)

        assert SECRET not in repr(auth)
        assert SECRET not in str(auth)
        assert SECRET not in f"auth={auth}"

    def test_an_empty_credential_is_refused(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            BearerTokenAuth("")


class TestTheCredentialTravelsInOnePlace:
    """The header, and nowhere else."""

    def test_it_is_attached_to_the_outgoing_request(self):
        import httpx

        request = httpx.Request("POST", "http://mail-mcp-gmail:9100/mcp")

        flow = BearerTokenAuth(SECRET).auth_flow(request)
        prepared = next(flow)

        assert prepared.headers["Authorization"] == f"Bearer {SECRET}"
