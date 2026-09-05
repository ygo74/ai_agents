"""Reasoning port backed by a Microsoft Agent Framework chat client."""

from __future__ import annotations

from typing import cast

from agent_framework import ChatOptions, ChatResponse, Message, SupportsChatGetResponse

from ai_agent_lab.domain.reasoning.envelope import PromptEnvelopeBuilder
from ai_agent_lab.domain.reasoning.errors import ReasoningOutputError, ReasoningUnavailableError
from ai_agent_lab.domain.reasoning.ports import ReasoningOutputT, ReasoningRequest


class MafTextReasoner:
    """Implements :class:`TextReasoner` with a framework chat client.

    The prompt is assembled by the domain envelope builder, not here, so the
    untrusted-content fencing is identical whichever framework is in use.
    """

    def __init__(
        self,
        client: SupportsChatGetResponse,
        envelope_builder: PromptEnvelopeBuilder,
        *,
        temperature: float = 0.0,
    ) -> None:
        self._client = client
        self._envelope_builder = envelope_builder
        self._temperature = temperature

    async def reason(
        self,
        request: ReasoningRequest,
        response_model: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        """Return a validated instance of ``response_model``."""
        prompt = self._envelope_builder.build(request)
        response = await self._get_response(prompt, response_model)
        return self._extract(response, response_model)

    async def _get_response(
        self,
        prompt: str,
        response_model: type[ReasoningOutputT],
    ) -> ChatResponse[ReasoningOutputT]:
        """Call the chat client, translating transport failures."""
        options = ChatOptions(response_format=response_model, temperature=self._temperature)
        try:
            return cast(
                ChatResponse[ReasoningOutputT],
                await self._client.get_response([Message(role="user", contents=[prompt])], options=options),
            )
        except Exception as error:
            raise ReasoningUnavailableError(f"the reasoning backend failed: {type(error).__name__}") from error

    @staticmethod
    def _extract(
        response: ChatResponse[ReasoningOutputT],
        response_model: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        """Validate the structured answer produced by the model.

        ``ChatResponse.value`` parses lazily and raises when the answer does not
        match the requested shape, so reading it belongs inside the guarded
        block. The failure is reported without echoing the offending text: it is
        derived from mail content and would otherwise reach logs and traces
        through the framework's error handling.
        """
        try:
            value = response.value
        except ValueError:
            value = None
        if isinstance(value, response_model):
            return value
        if not response.text:
            raise ReasoningOutputError(f"the model returned no {response_model.__name__}")
        try:
            return response_model.model_validate_json(response.text)
        except ValueError as error:
            raise ReasoningOutputError(f"the model returned an invalid {response_model.__name__}") from error
