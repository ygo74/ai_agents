"""Construction of the chat client backing the agent.

Microsoft Agent Framework 1.17 exposes a single unified client for both model
providers: the ``AzureOpenAI*`` compatibility classes were removed from
``agent_framework.azure``. Azure OpenAI is therefore selected by explicit
routing inputs - ``azure_endpoint``/``base_url`` or ``credential`` - and not by
a different class.

Making that selection explicit matters: without a routing input the client stays
on OpenAI whenever ``OPENAI_API_KEY`` is set, even when ``AZURE_OPENAI_*``
variables are configured, which would silently ignore an Azure configuration.

No credential is handled here. With an API key the framework client reads it
from the environment; with Entra ID it receives a credential object whose token
never reaches the application, a prompt or a log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_framework import SupportsChatGetResponse
from agent_framework.openai import OpenAIChatClient

from ai_agent_lab.domain.errors import DomainError

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential


class ChatClientConfigurationError(DomainError):
    """Raised when the requested chat provider cannot be honoured."""


# The credential is passed straight to the client, which exchanges it for a
# token itself. Aliasing it keeps the Azure SDK out of the callers' imports.
type AzureCredential = TokenCredential


@dataclass(frozen=True, slots=True)
class AzureOpenAIRoute:
    """Where an Azure OpenAI deployment lives.

    ``endpoint`` accepts the resource URL as well as the complete
    ``.../openai/v1`` form shown by the portal; both are normalised to the
    resource URL the client expects.
    """

    model: str
    endpoint: str = ""
    api_version: str = ""


class MafChatClientFactory:
    """Builds the chat client of a given provider.

    The agent, the skills and the confirmation policy are identical whichever
    provider is selected; only the object built here changes.

    Credentials are never handled here. The client resolves its own key from the
    environment, or exchanges an Entra ID credential for a token itself.
    """

    def openai(self, *, model: str = "") -> SupportsChatGetResponse:
        """Build the direct OpenAI client, which resolves its own key."""
        if not model:
            return OpenAIChatClient()
        return OpenAIChatClient(model=model)

    def azure_openai(
        self,
        route: AzureOpenAIRoute,
        *,
        credential: AzureCredential | None = None,
    ) -> SupportsChatGetResponse:
        """Build the Azure OpenAI client with an explicit routing input.

        The endpoint is always passed as ``azure_endpoint``. Passing it as
        ``base_url`` would leave the client on the OpenAI path, where it looks
        for ``OPENAI_API_KEY`` and never sees the Azure key.
        """
        self._require_route(route)
        return OpenAIChatClient(
            model=route.model,
            azure_endpoint=self._normalised_endpoint(route.endpoint),
            credential=credential,
            api_version=route.api_version or None,
        )

    @staticmethod
    def _normalised_endpoint(endpoint: str) -> str:
        """Return the resource endpoint without the API surface segment.

        The client appends ``/openai/v1`` to an ``azure_endpoint``. An endpoint
        that already carries it - what the Azure portal shows for the
        OpenAI-compatible surface - would otherwise produce a duplicated
        ``/openai/v1/openai/v1/`` path and 404 on every call.
        """
        trimmed = endpoint.rstrip("/")
        suffix = "/openai/v1"
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)]
        return endpoint

    @staticmethod
    def _require_route(route: AzureOpenAIRoute) -> None:
        """Refuse an Azure route the client could not resolve."""
        if not route.model:
            raise ChatClientConfigurationError(
                "the azure_openai provider requires a deployment name (AZURE_OPENAI_CHAT_MODEL)"
            )
        if not route.endpoint:
            raise ChatClientConfigurationError(
                "the azure_openai provider requires AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_BASE_URL"
            )
