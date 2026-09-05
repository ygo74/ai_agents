"""Configuration of the Mail Agent.

Only non-sensitive settings live here. Credentials are never read, held or
logged by the application: the chat client reads its own key from the
environment, and mail credentials belong to the MCP server.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_agent_lab.domain.security.confirmation import ConfirmationPreferences


class MailAgentMode(StrEnum):
    """Where the mail data comes from."""

    MOCK = "mock"
    MCP = "mcp"


class McpTransport(StrEnum):
    """How the MCP client reaches the mail server."""

    STDIO = "stdio"
    HTTP = "http"


class MailAgentSettings(BaseSettings):
    """Runtime settings of the Mail Agent, read from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="MAIL_AGENT_",
        env_file=".env",
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


class MailMcpSettings(BaseSettings):
    """Connection settings of the mail MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="MAIL_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    transport: McpTransport = McpTransport.STDIO
    command: str = ""
    args: str = ""
    url: str = ""
    request_timeout_seconds: int = 30

    def command_args(self) -> tuple[str, ...]:
        """Arguments passed to a stdio MCP server."""
        return tuple(part for part in self.args.split() if part)


def _names(value: str) -> frozenset[str]:
    """Split a comma-separated list of tool names."""
    return frozenset(part.strip() for part in value.split(",") if part.strip())
