"""Deterministic reasoner used by tests and by the offline mock mode.

Replaying a scripted answer instead of calling a model keeps unit tests fast,
free and reproducible, and lets the mock runtime mode run with no API key at
all. It implements the same :class:`TextReasoner` port as the real adapter, so
the skills under test are exactly the ones that run in production.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ValidationError
from ygo74.agent_runtime.domains.security.prompt_envelope import PromptEnvelopeBuilder

from ai_agent_lab.core.reasoning.errors import ReasoningOutputError
from ai_agent_lab.core.reasoning.ports import ReasoningOutputT, ReasoningRequest

_logger = logging.getLogger(__name__)


class RecordedReasoning(BaseModel):
    """One reasoning call, captured for assertions."""

    model_config = {"frozen": True}

    task: str
    instructions: str
    rendered_prompt: str


class ScriptedTextReasoner:
    """Returns a pre-registered answer for each expected output type.

    Args:
        answers: Payload to return, keyed by the requested output model.
        envelope_builder: Optional builder used to render, and therefore to
            exercise, the untrusted-content fencing during tests.
    """

    def __init__(
        self,
        answers: Mapping[type[BaseModel], Mapping[str, object]],
        *,
        envelope_builder: PromptEnvelopeBuilder | None = None,
    ) -> None:
        _logger.info("Initializing scripted Mail reasoner")
        _logger.debug(
            "ScriptedTextReasoner.__init__ arguments: response_models=%s, envelope_builder_type=%s",
            tuple(sorted(model.__name__ for model in answers)),
            None if envelope_builder is None else type(envelope_builder).__name__,
        )
        self._answers = dict(answers)
        self._envelope_builder = envelope_builder
        self._calls: list[RecordedReasoning] = []

    @property
    def calls(self) -> Sequence[RecordedReasoning]:
        """Every reasoning call performed so far."""
        return tuple(self._calls)

    async def reason(
        self,
        request: ReasoningRequest,
        response_model: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        """Return the answer registered for ``response_model``."""
        _logger.info("Running scripted Mail reasoning")
        _logger.debug(
            "ScriptedTextReasoner.reason arguments: response_model=%s, "
            "instructions_length=%d, task_length=%d, context_sections=%d",
            response_model.__name__,
            len(request.instructions),
            len(request.task),
            len(request.context),
        )
        self._record(request)
        payload = self._answers.get(response_model)
        if payload is None:
            raise ReasoningOutputError(f"no scripted answer registered for {response_model.__name__}")
        try:
            return response_model.model_validate(payload)
        except ValidationError as error:
            raise ReasoningOutputError(f"scripted answer does not match {response_model.__name__}: {error}") from error

    def _record(self, request: ReasoningRequest) -> None:
        """Capture a call, rendering the prompt when a builder was supplied."""
        _logger.info("Recording scripted Mail reasoning call")
        _logger.debug(
            "ScriptedTextReasoner._record arguments: instructions_length=%d, "
            "task_length=%d, context_sections=%d, render_prompt=%s",
            len(request.instructions),
            len(request.task),
            len(request.context),
            self._envelope_builder is not None,
        )
        rendered = "" if self._envelope_builder is None else self._envelope_builder.build(request)
        self._calls.append(
            RecordedReasoning(
                task=request.task,
                instructions=request.instructions,
                rendered_prompt=rendered,
            )
        )
