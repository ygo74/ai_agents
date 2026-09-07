"""Entra ID credentials for the Azure OpenAI deployment.

Only this module knows ``azure-identity``. It hands a credential object to the
chat client, which exchanges it for a token itself: no token, key or secret ever
crosses into the application, a prompt or a log.
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

    @staticmethod
    def _factories() -> dict[AzureCredentialMode, Callable[[], TokenCredential]]:
        """Return the supported Entra ID credential factories."""
        try:
            from azure.identity import AzureCliCredential, DefaultAzureCredential
        except ImportError as error:
            raise AzureCredentialUnavailableError(
                "Entra ID authentication needs the 'azure' extra: pip install -e \".[maf,azure]\""
            ) from error
        return {
            AzureCredentialMode.AZURE_CLI: AzureCliCredential,
            AzureCredentialMode.DEFAULT: DefaultAzureCredential,
        }
