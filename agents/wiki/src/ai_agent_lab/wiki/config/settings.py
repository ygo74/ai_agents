"""Configuration of the Wiki Agent.

Only non-sensitive settings live here. Credentials are never read, held or logged
by the application: the chat model reads its own key from the environment, and
Confluence credentials belong to the MCP server process.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from ygo74.agent_runtime.domains.humanapproval.confirmation import ConfirmationPreferences

from ai_agent_lab.core.config.chat import AzureCredentialMode, ChatProvider
from ai_agent_lab.core.config.environment import ENV_FILE
from ai_agent_lab.wiki.domain.auth import WikiAuthScheme

__all__ = [
    "ENV_FILE",
    "AzureCredentialMode",
    "ChatModelSettings",
    "ChatProvider",
    "WikiAgentMode",
    "WikiAgentSettings",
    "WikiAuthScheme",
    "WikiFreshnessSettings",
    "WikiMcpSettings",
]


class WikiAgentMode(StrEnum):
    """Where the wiki data comes from."""

    MOCK = "mock"
    MCP = "mcp"


class WikiAgentSettings(BaseSettings):
    """Runtime settings of the Wiki Agent, read from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="WIKI_AGENT_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: WikiAgentMode = WikiAgentMode.MOCK
    mock_dataset: Path = Path("data/wiki/sample_wiki.json")
    user_id: str = "local-user"
    log_level: str = "INFO"

    # Comma-separated tool names. Kept as plain text so a malformed value fails
    # with a readable message instead of a JSON decoding error.
    auto_approved_tools: str = ""
    always_confirm_tools: str = ""

    def confirmation_preferences(self) -> ConfirmationPreferences:
        """Build the confirmation preferences of the configured user."""
        return ConfirmationPreferences(
            auto_approved_tools=_names(self.auto_approved_tools),
            always_confirm_tools=_names(self.always_confirm_tools),
        )


class WikiMcpSettings(BaseSettings):
    """Which wiki MCP server the agent is bound to, and how it authenticates."""

    model_config = SettingsConfigDict(
        env_prefix="WIKI_MCP_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server: str = "wiki-local"
    timeout_seconds: int = 30

    # The account a single-identity connection acts for. `sooperset/mcp-atlassian`
    # over stdio has one set of credentials and no per-request identity, so the
    # agent must know whose view of the wiki it is actually getting. Empty means
    # the server scopes results itself, which is what our own protocol does.
    account_id: str = ""

    # How a caller identifies itself over HTTP: none | basic | token | bearer.
    #
    #   basic   Confluence Cloud, `Basic <base64(email:api_token)>`
    #   token   Confluence Data Center, `Token <personal access token>`
    #   bearer  either, with OAuth - but the server downgrades it to a Data
    #           Center PAT when it has no OAuth configuration, so say `token`
    #           when a PAT is what you mean.
    #
    # `none` is right for stdio and for our own protocol server, which carries
    # the caller's identity as a tool argument instead.
    auth_scheme: WikiAuthScheme = WikiAuthScheme.NONE

    # The credential of the local user, for the proof of concept.
    #
    # This is the seam where a real deployment differs. Here there is one local
    # user and no identity provider, so the credential is configured. Serving
    # several people means minting an on-behalf-of token for the authenticated
    # caller and supplying it per request; only the WikiUserCredentials
    # implementation changes, and nothing above the MCP boundary notices.
    user_account: str = ""
    user_secret: SecretStr = SecretStr("")


class WikiFreshnessSettings(BaseSettings):
    """When documentation stops being trustworthy.

    These are a judgement about a particular body of documentation - a coding
    standard ages slowly, a sprint plan ages in weeks - so they are configuration
    rather than code.
    """

    model_config = SettingsConfigDict(
        env_prefix="WIKI_FRESHNESS_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ageing_after_days: int = 90
    stale_after_days: int = 180


class ChatModelSettings(BaseSettings):
    """Selection of the chat model that backs the agent.

    Only routing information lives here. No API key is ever read, held or logged
    by the application: the LangChain client resolves credentials itself, from
    the environment or from Entra ID.

    The variable names are **the same ones the Mail Agent reads**, on purpose.
    Both agents must run against the same model, from the same ``.env``, or a
    comparison between the two frameworks would be measuring two different
    deployments. That is why every field is aliased rather than prefixed.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: ChatProvider = Field(default=ChatProvider.OPENAI, validation_alias="AGENT_CHAT_PROVIDER")
    openai_model: str = Field(default="", validation_alias="OPENAI_CHAT_MODEL")
    # Kept as text: an empty value means "do not send it at all", which no
    # numeric type can express, and reasoning models reject the parameter.
    temperature: str = Field(default="", validation_alias="AGENT_CHAT_TEMPERATURE")
    azure_model: str = Field(default="", validation_alias="AZURE_OPENAI_CHAT_MODEL")
    azure_endpoint: str = Field(default="", validation_alias="AZURE_OPENAI_ENDPOINT")
    azure_api_version: str = Field(default="", validation_alias="AZURE_OPENAI_API_VERSION")
    azure_credential: AzureCredentialMode = Field(
        default=AzureCredentialMode.API_KEY,
        validation_alias="AZURE_OPENAI_CREDENTIAL",
    )

    def sampling_temperature(self) -> float | None:
        """Return the configured temperature, or nothing when it must be omitted.

        Reasoning models refuse the parameter outright, so it is only sent when a
        value was configured.
        """
        value = self.temperature.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(f"AGENT_CHAT_TEMPERATURE must be a number or empty, got {value!r}") from error


def _names(value: str) -> frozenset[str]:
    """Split a comma-separated list of tool names."""
    return frozenset(name.strip() for name in value.split(",") if name.strip())
