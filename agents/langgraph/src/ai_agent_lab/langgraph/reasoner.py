"""Reasoning port backed by a LangChain chat model.

The prompt is assembled by the shared envelope builder, not here, so the
untrusted-content fencing is identical whichever framework is in use. That is
the point of the port: a skill produces a :class:`ReasoningRequest` and never
learns which framework answered it.

Structured output is obtained through ``with_structured_output``, which is where
LangChain and Microsoft Agent Framework differ in an interesting way. MAF returns
a response whose ``value`` parses lazily and may fail on read; LangChain returns
the parsed model directly, or raises. Both failure modes are translated here into
the same two domain errors, so a skill sees one behaviour.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from ygo74.agent_runtime.domains.security.prompt_envelope import PromptEnvelopeBuilder

from ai_agent_lab.core.reasoning.errors import ReasoningOutputError, ReasoningUnavailableError
from ai_agent_lab.core.reasoning.ports import ReasoningOutputT, ReasoningRequest

_logger = logging.getLogger(__name__)


class LangGraphTextReasoner:
    """Implements :class:`TextReasoner` with a LangChain chat model.

    ``temperature`` is omitted when it is ``None``. Reasoning models reject the
    parameter outright, so binding it unconditionally would make every analysis
    fail against such a deployment.
    """

    def __init__(
        self,
        model: BaseChatModel,
        envelope_builder: PromptEnvelopeBuilder,
        *,
        temperature: float | None = None,
    ) -> None:
        self._model = model
        self._envelope_builder = envelope_builder
        self._temperature = temperature

    async def reason(
        self,
        request: ReasoningRequest,
        response_model: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        """Return a validated instance of ``response_model``."""
        _logger.info("Executing reasoning request -> target_model=%s", response_model.__name__)
        _logger.debug(
            "Reasoning request details: instructions_length=%d, context_items=%d, temperature=%s",
            len(request.instructions),
            len(request.context),
            self._temperature,
        )
        prompt = self._envelope_builder.build(request)
        _logger.debug("Built reasoning prompt envelope (length=%d)", len(prompt))
        answer = await self._invoke(prompt, response_model)
        validated = self._validated(answer, response_model)
        _logger.info("Reasoning completed successfully for %s", response_model.__name__)
        _logger.debug("Reasoning output: %s", validated)
        return validated

    async def _invoke(
        self,
        prompt: str,
        response_model: type[ReasoningOutputT],
    ) -> object:
        """Call the model, translating transport failures.

        The prompt is sent as a single human message. It already carries the
        instructions, the task and the fenced material in the order the envelope
        builder decided, and splitting it across a system and a human message
        here would let the two frameworks send different prompts for the same
        request - which would quietly invalidate the comparison.
        """
        structured = self._structured(response_model)
        try:
            _logger.debug("Invoking structured output chat model for %s", response_model.__name__)
            return await structured.ainvoke([HumanMessage(content=prompt)])
        except Exception as error:
            _logger.warning("Reasoning invocation failed: %s (%s)", type(error).__name__, error)
            raise ReasoningUnavailableError(f"the reasoning backend failed: {type(error).__name__}") from error

    def _structured(self, response_model: type[ReasoningOutputT]) -> Runnable[Any, Any]:
        """Bind the response shape, and the temperature when one was asked for."""
        model = self._model if self._temperature is None else self._model.bind(temperature=self._temperature)
        return model.with_structured_output(response_model)

    @staticmethod
    def _validated(
        answer: object,
        response_model: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        """Confirm the model returned the shape that was requested.

        The failure is reported without echoing the offending text: it is derived
        from third-party content and would otherwise reach logs and traces.
        """
        if isinstance(answer, response_model):
            return answer
        _logger.warning(
            "the model returned a %s where a %s was required",
            type(answer).__name__,
            response_model.__name__,
        )
        raise ReasoningOutputError(f"the model returned no {response_model.__name__}")
