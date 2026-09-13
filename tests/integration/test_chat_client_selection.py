"""Tests of the chat client selection.

The Mail Agent must reach the provider the configuration names. The trap this
suite exists for is real: the unified client stays on OpenAI whenever
``OPENAI_API_KEY`` is set, even when every ``AZURE_OPENAI_*`` variable is
configured, so an implicit selection would silently ignore an Azure deployment.

No test performs a network call: only the client object built locally is
inspected.
"""

from __future__ import annotations

import pytest
from openai import AsyncAzureOpenAI, AsyncOpenAI

from ai_agent_lab.core.config.azure_credentials import (
    AzureCredentialUnavailableError,
    AzureIdentityCredentialProvider,
)
from ai_agent_lab.maf.chat_client import (
    AzureOpenAIRoute,
    ChatClientConfigurationError,
    MafChatClientFactory,
)
from ai_agent_lab.mail.application.chat_client import ConfiguredChatClientFactory
from ai_agent_lab.mail.config.settings import (
    AzureCredentialMode,
    ChatClientSettings,
    ChatProvider,
)

AZURE_ENDPOINT = "https://example-resource.openai.azure.com"
AZURE_DEPLOYMENT = "gpt-4o-mini-deployment"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Run every case against an explicit environment, never the developer's.

    The settings read a ``.env`` file by default; the working directory is moved
    so a local one cannot decide the outcome of a test.
    """
    for name in (
        "AGENT_CHAT_PROVIDER",
        "OPENAI_API_KEY",
        "OPENAI_CHAT_MODEL",
        "OPENAI_MODEL",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_CHAT_MODEL",
        "AZURE_OPENAI_MODEL",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_BASE_URL",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_CREDENTIAL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def build_client(monkeypatch, **environment: str):
    """Build the chat client the given environment asks for."""
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    return ConfiguredChatClientFactory(
        ChatClientSettings(),
        MafChatClientFactory(),
        AzureIdentityCredentialProvider(),
    ).build()


class TestProviderSelection:
    """The configured provider is the provider that gets built."""

    def test_openai_is_the_default_provider(self, monkeypatch):
        client = build_client(monkeypatch, OPENAI_API_KEY="openai-key", OPENAI_CHAT_MODEL="gpt-4o-mini")

        assert isinstance(client.client, AsyncOpenAI)
        assert not isinstance(client.client, AsyncAzureOpenAI)
        assert client.model == "gpt-4o-mini"

    def test_azure_openai_is_built_when_configured(self, monkeypatch):
        client = build_client(
            monkeypatch,
            AGENT_CHAT_PROVIDER="azure_openai",
            AZURE_OPENAI_API_KEY="azure-key",
            AZURE_OPENAI_ENDPOINT=AZURE_ENDPOINT,
            AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
        )

        assert isinstance(client.client, AsyncAzureOpenAI)
        assert client.model == AZURE_DEPLOYMENT

    def test_azure_wins_over_a_configured_openai_key(self, monkeypatch):
        """The regression this module exists for.

        Both providers configured is the normal case of ``.env.example``. An
        implicit selection silently stays on OpenAI and ignores Azure.
        """
        client = build_client(
            monkeypatch,
            AGENT_CHAT_PROVIDER="azure_openai",
            OPENAI_API_KEY="openai-key",
            OPENAI_CHAT_MODEL="gpt-4o-mini",
            AZURE_OPENAI_API_KEY="azure-key",
            AZURE_OPENAI_ENDPOINT=AZURE_ENDPOINT,
            AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
        )

        assert isinstance(client.client, AsyncAzureOpenAI)
        assert client.model == AZURE_DEPLOYMENT

    def test_openai_is_kept_when_azure_variables_are_present(self, monkeypatch):
        client = build_client(
            monkeypatch,
            AGENT_CHAT_PROVIDER="openai",
            OPENAI_API_KEY="openai-key",
            OPENAI_CHAT_MODEL="gpt-4o-mini",
            AZURE_OPENAI_API_KEY="azure-key",
            AZURE_OPENAI_ENDPOINT=AZURE_ENDPOINT,
            AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
        )

        assert not isinstance(client.client, AsyncAzureOpenAI)
        assert client.model == "gpt-4o-mini"

    def test_an_unknown_provider_is_refused(self, monkeypatch):
        monkeypatch.setenv("AGENT_CHAT_PROVIDER", "bedrock")

        with pytest.raises(ValueError, match="bedrock"):
            ChatClientSettings()


class TestAzureRouting:
    """Azure needs a route the client can resolve, and says so when it lacks one."""

    def test_a_base_url_is_refused_with_a_usable_message(self, monkeypatch):
        """A base URL cannot be combined with an endpoint by the client.

        Left alone it also falls back to the OpenAI path, where the Azure key is
        never read, so it is refused here with an actionable message.
        """
        with pytest.raises(ChatClientConfigurationError, match="AZURE_OPENAI_ENDPOINT"):
            build_client(
                monkeypatch,
                AGENT_CHAT_PROVIDER="azure_openai",
                AZURE_OPENAI_API_KEY="azure-key",
                AZURE_OPENAI_BASE_URL=f"{AZURE_ENDPOINT}/openai/v1",
                AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
            )

    def test_an_endpoint_already_carrying_the_api_surface_is_not_duplicated(self, monkeypatch):
        """A portal URL ending in ``/openai/v1`` must not gain a second segment.

        The client appends ``/openai/v1`` to an ``azure_endpoint``; without the
        normalisation the URL ends in ``/openai/v1/openai/v1/`` and calls 404.
        """
        client = build_client(
            monkeypatch,
            AGENT_CHAT_PROVIDER="azure_openai",
            AZURE_OPENAI_API_KEY="azure-key",
            AZURE_OPENAI_ENDPOINT=f"{AZURE_ENDPOINT}/openai/v1",
            AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
        )

        resolved = str(client.client.base_url)
        assert "/openai/v1/openai/v1" not in resolved
        assert resolved.rstrip("/").endswith("/openai/v1")

    def test_a_bare_endpoint_is_completed_by_the_client(self, monkeypatch):
        client = build_client(
            monkeypatch,
            AGENT_CHAT_PROVIDER="azure_openai",
            AZURE_OPENAI_API_KEY="azure-key",
            AZURE_OPENAI_ENDPOINT=AZURE_ENDPOINT,
            AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
        )

        assert str(client.client.base_url).rstrip("/").endswith("/openai/v1")

    def test_a_missing_endpoint_is_reported(self, monkeypatch):
        with pytest.raises(ChatClientConfigurationError, match="AZURE_OPENAI_ENDPOINT"):
            build_client(
                monkeypatch,
                AGENT_CHAT_PROVIDER="azure_openai",
                AZURE_OPENAI_API_KEY="azure-key",
                AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
            )

    def test_a_missing_deployment_is_reported(self, monkeypatch):
        with pytest.raises(ChatClientConfigurationError, match="AZURE_OPENAI_CHAT_MODEL"):
            build_client(
                monkeypatch,
                AGENT_CHAT_PROVIDER="azure_openai",
                AZURE_OPENAI_API_KEY="azure-key",
                AZURE_OPENAI_ENDPOINT=AZURE_ENDPOINT,
            )

    def test_the_api_version_is_forwarded(self, monkeypatch):
        client = build_client(
            monkeypatch,
            AGENT_CHAT_PROVIDER="azure_openai",
            AZURE_OPENAI_API_KEY="azure-key",
            AZURE_OPENAI_ENDPOINT=AZURE_ENDPOINT,
            AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
            AZURE_OPENAI_API_VERSION="2026-01-01",
        )

        assert client.client._api_version == "2026-01-01"


@pytest.mark.security
class TestEntraIdAuthentication:
    """A key is one option, not the only one."""

    def test_entra_id_replaces_the_api_key(self, monkeypatch):
        client = build_client(
            monkeypatch,
            AGENT_CHAT_PROVIDER="azure_openai",
            AZURE_OPENAI_ENDPOINT=AZURE_ENDPOINT,
            AZURE_OPENAI_CHAT_MODEL=AZURE_DEPLOYMENT,
            AZURE_OPENAI_CREDENTIAL="azure_cli",
        )

        assert isinstance(client.client, AsyncAzureOpenAI)
        assert client.client._azure_ad_token_provider is not None

    def test_an_api_key_mode_asks_for_no_credential(self):
        with pytest.raises(AzureCredentialUnavailableError, match="api_key"):
            AzureIdentityCredentialProvider().create(AzureCredentialMode.API_KEY)

    def test_no_secret_is_stored_in_the_settings(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "openai-secret-value")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret-value")

        rendered = repr(ChatClientSettings().model_dump())

        assert "openai-secret-value" not in rendered
        assert "azure-secret-value" not in rendered


class TestRouteContract:
    """The framework adapter is usable on its own, without any environment."""

    def test_a_route_without_a_destination_is_refused(self):
        with pytest.raises(ChatClientConfigurationError):
            MafChatClientFactory().azure_openai(AzureOpenAIRoute(model=AZURE_DEPLOYMENT))

    def test_the_settings_expose_the_endpoint_as_configured(self, monkeypatch):
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", f"{AZURE_ENDPOINT}/openai/v1")

        assert ChatClientSettings().azure_endpoint.endswith("/openai/v1")

    def test_a_portal_url_is_normalised_for_the_client(self):
        normalised = MafChatClientFactory._normalised_endpoint(f"{AZURE_ENDPOINT}/openai/v1")

        assert normalised == AZURE_ENDPOINT

    def test_the_provider_defaults_to_openai(self):
        assert ChatClientSettings().provider is ChatProvider.OPENAI
