"""Entra ID credentials for an Azure OpenAI deployment.

Only this module knows ``azure-identity``. It hands a credential object to a chat
client, which exchanges it for a token itself: no token, key or secret ever
crosses into the application, a prompt or a log.

It lives in the core rather than in a framework adapter because it holds no
framework knowledge at all, and because every adapter needs exactly this. A copy
per framework would be one copy away from one of them reporting a missing
optional dependency as a bare ``ImportError``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ai_agent_lab.core.config.chat import AzureCredentialMode
from ai_agent_lab.core.errors import DomainError

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential


class AzureCredentialUnavailableError(DomainError):
    """Raised when the requested Entra ID credential cannot be built."""


class AzureIdentityCredentialProvider:
    """Builds Entra ID credentials with ``azure-identity``.

    The package is an optional extra, so it is imported on demand: an OpenAI or
    API-key deployment must not require it to be installed.
    """

    def create(self, mode: AzureCredentialMode) -> TokenCredential:
        """Return the credential matching the requested mode."""
        factory = self._factories().get(mode)
        if factory is None:
            raise AzureCredentialUnavailableError(f"credential mode {mode.value!r} does not use Entra ID")
        return factory()

    def create_or_none(self, mode: AzureCredentialMode) -> TokenCredential | None:
        """Return a credential, or nothing when the mode uses an API key.

        With ``api_key`` there is no credential at all: the client reads the key
        from the environment itself, and the application never holds one. Callers
        that route on the mode want this rather than an exception.
        """
        if mode is AzureCredentialMode.API_KEY:
            return None
        return self.create(mode)

    @staticmethod
    def _factories() -> dict[AzureCredentialMode, Callable[[], TokenCredential]]:
        """Return the supported Entra ID credential factories."""
        try:
            from azure.identity import AzureCliCredential, DefaultAzureCredential
        except ImportError as error:
            raise AzureCredentialUnavailableError(
                "Entra ID authentication needs the 'azure' extra of the framework adapter"
            ) from error
        return {
            AzureCredentialMode.AZURE_CLI: AzureCliCredential,
            AzureCredentialMode.DEFAULT: DefaultAzureCredential,
        }
