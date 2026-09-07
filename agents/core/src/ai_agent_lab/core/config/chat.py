"""How an agent reaches its model provider.

These choices belong to no single agent: the Mail Agent and whatever comes after
it authenticate the same way. Keeping them here also keeps the framework adapter
free of any agent, since it needs the credential mode and nothing else.
"""

from __future__ import annotations

from enum import StrEnum


class ChatProvider(StrEnum):
    """Which model provider backs an agent."""

    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"


class AzureCredentialMode(StrEnum):
    """How an agent authenticates against Azure OpenAI.

    ``API_KEY`` leaves the key to the framework client, which reads it from the
    environment. The other modes use Entra ID, so no key exists at all.
    """

    API_KEY = "api_key"
    AZURE_CLI = "azure_cli"
    DEFAULT = "default"
