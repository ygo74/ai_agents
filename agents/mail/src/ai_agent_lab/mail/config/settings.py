"""Configuration of the Mail Agent.

Only non-sensitive settings live here. Credentials are never read, held or
logged by the application: the chat client reads its own key from the
environment, and mail credentials belong to the MCP server.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from ygo74.agent_runtime.domains.humanapproval.confirmation import ConfirmationPreferences

from ai_agent_lab.core.config.chat import AzureCredentialMode, ChatProvider
from ai_agent_lab.core.config.environment import ENV_FILE
from ai_agent_lab.mail.mail_errors import MailAgentConfigurationError

__all__ = [
    "ENV_FILE",
    "AzureCredentialMode",
    "ChatClientSettings",
    "ChatProvider",
    "MailAgentMode",
    "MailAgentSettings",
    "MailMcpAuthScheme",
    "MailMcpSettings",
]


class MailAgentMode(StrEnum):
    """Where the mail data comes from."""

    MOCK = "mock"
    MCP = "mcp"


class MailAgentSettings(BaseSettings):
    """Runtime settings of the Mail Agent, read from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="MAIL_AGENT_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: MailAgentMode = MailAgentMode.MOCK
    mock_dataset: Path = Path("data/mail/sample_mailbox.json")
    user_id: str = "local-user"
    user_email: str = "local-user@example.com"
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


class ChatClientSettings(BaseSettings):
    """Selection of the chat client that backs the agent.

    Only routing information lives here. No API key is ever read, held or logged
    by the application: the framework client resolves credentials itself, from
    the environment or from Entra ID.

    The provider is explicit on purpose. The unified client stays on OpenAI
    whenever ``OPENAI_API_KEY`` is set, even when ``AZURE_OPENAI_*`` variables
    are present, so an implicit selection would silently ignore an Azure
    configuration.
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
    # Read only to reject it: the client refuses an endpoint and a base URL at
    # the same time, and the endpoint alone covers both forms.
    azure_base_url: str = Field(default="", validation_alias="AZURE_OPENAI_BASE_URL")

    def sampling_temperature(self) -> float | None:
        """Return the configured temperature, or nothing when it must be omitted.

        Reasoning models refuse the parameter outright, so it is only sent when
        a value was configured.
        """
        value = self.temperature.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(f"AGENT_CHAT_TEMPERATURE must be a number or empty, got {value!r}") from error


class MailMcpAuthScheme(StrEnum):
    """How the agent proves itself to a mail MCP server reached over HTTP.

    A stdio server needs nothing: it is a child process, trusted through the
    operating system. Over HTTP the question is real, and the two answers are not
    interchangeable.

    ``oauth``
        Google's own endpoint. The agent runs the authorisation-code flow and
        holds a token scoped to the mailbox.
    ``bearer``
        Our own server, deployed alongside. The shared secret says "you are the
        agent I was deployed with" - the mailbox identity was already settled by
        the credential that server holds.
    """

    OAUTH = "oauth"
    BEARER = "bearer"


class MailMcpSettings(BaseSettings):
    """Connection settings of the mail MCP server.

    Where the server lives and which tools it exposes are delivered in
    ``config/mcp/<server>.yaml``; only the choice of server, the timeout and how
    to authenticate are environment concerns.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAIL_MCP_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server: str = "local"
    request_timeout_seconds: int = 30

    # Defaulting to OAuth keeps every existing deployment behaving as it did:
    # before this setting existed, an HTTP binding always meant Google.
    auth_scheme: MailMcpAuthScheme = MailMcpAuthScheme.OAUTH

    # The shared secret of a `bearer` deployment. Held as `SecretStr` so logging
    # a settings object cannot leak it.
    http_token: SecretStr = SecretStr("")

    def bearer_token(self) -> str:
        """Return the shared secret, or say plainly that none was configured."""
        token = self.http_token.get_secret_value().strip()
        if not token:
            raise MailAgentConfigurationError(
                "MAIL_MCP_AUTH_SCHEME is 'bearer' but MAIL_MCP_HTTP_TOKEN is empty: "
                "the agent has nothing to present, and the server will refuse every call"
            )
        return token


def _names(value: str) -> frozenset[str]:
    """Split a comma-separated list of tool names."""
    return frozenset(part.strip() for part in value.split(",") if part.strip())
