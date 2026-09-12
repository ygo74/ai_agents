"""Construction of the chat model backing a LangGraph agent.

No credential is handled here. With an API key the LangChain client reads it
from the environment; with Entra ID it receives a credential object, exchanges
it for a token itself, and the token never reaches the application, a prompt or
a log.

Azure OpenAI is a different class in LangChain (``AzureChatOpenAI``) rather than
a routing input on one client, which is the first small divergence from the
Microsoft Agent Framework adapter and worth recording for the comparison: it
removes a whole category of misconfiguration - there is no way to end up on the
OpenAI path while Azure variables are set - at the cost of a second import.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from ai_agent_lab.core.errors import DomainError

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

_logger = logging.getLogger(__name__)


class ChatModelConfigurationError(DomainError):
    """Raised when the requested chat provider cannot be honoured."""


# The credential is passed straight to the client, which exchanges it for a
# token itself. Aliasing it keeps the Azure SDK out of the callers' imports.
type AzureCredential = TokenCredential

DEFAULT_AZURE_API_VERSION = "2024-10-21"

# Scope of an Azure OpenAI access token. The client calls this provider to
# obtain one; it never sees the credential's secret material.
_AZURE_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureOpenAIRoute:
    """Where an Azure OpenAI deployment lives.

    ``endpoint`` accepts the resource URL as well as the complete ``.../openai/v1``
    form shown by the portal; both are normalised to the resource URL the client
    expects.
    """

    model: str
    endpoint: str = ""
    api_version: str = ""


class LangGraphChatModelFactory:
    """Builds the chat model of a given provider.

    The agent, the skills and the confirmation policy are identical whichever
    provider is selected; only the object built here changes.
    """

    def openai(self, *, model: str = "") -> BaseChatModel:
        """Build the direct OpenAI client, which resolves its own key."""
        if not model:
            raise ChatModelConfigurationError("the openai provider requires a model name (OPENAI_CHAT_MODEL)")
        _logger.info("Building OpenAI chat model for model=%s", model)
        return ChatOpenAI(model=model)

    def azure_openai(
        self,
        route: AzureOpenAIRoute,
        *,
        credential: AzureCredential | None = None,
    ) -> BaseChatModel:
        """Build the Azure OpenAI client for one deployment.

        With a credential the client is given a token *provider* rather than a
        token, so it refreshes expired tokens itself. A long conversation would
        otherwise start failing partway through, once the first token expired.
        """
        self._require_route(route)
        norm_endpoint = self._normalised_endpoint(route.endpoint)
        api_ver = route.api_version or DEFAULT_AZURE_API_VERSION
        _logger.info(
            "Building Azure OpenAI chat model (deployment=%s, endpoint=%s, api_version=%s, entra_id=%s)",
            route.model,
            norm_endpoint,
            api_ver,
            credential is not None,
        )
        return AzureChatOpenAI(
            azure_deployment=route.model,
            azure_endpoint=norm_endpoint,
            api_version=api_ver,
            azure_ad_token_provider=self._token_provider(credential),
        )

    @staticmethod
    def _token_provider(credential: AzureCredential | None) -> Callable[[], str] | None:
        """Return a callable handing the client a fresh token, or nothing.

        Without a credential the client falls back to ``AZURE_OPENAI_API_KEY``,
        which it reads from the environment itself.
        """
        if credential is None:
            return None
        return lambda: credential.get_token(_AZURE_COGNITIVE_SCOPE).token

    @staticmethod
    def _normalised_endpoint(endpoint: str) -> str:
        """Return the resource endpoint without the API surface segment.

        The client appends the API path to an ``azure_endpoint``. An endpoint
        that already carries it - what the Azure portal shows for the
        OpenAI-compatible surface - would otherwise produce a duplicated path
        and 404 on every call.
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
            raise ChatModelConfigurationError(
                "the azure_openai provider requires a deployment name (AZURE_OPENAI_CHAT_MODEL)"
            )
        if not route.endpoint:
            raise ChatModelConfigurationError(
                "the azure_openai provider requires AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_BASE_URL"
            )
