"""Port through which capabilities obtain language-model reasoning.

Capabilities must stay usable with Microsoft Agent Framework, LangChain or CrewAI,
so they never depend on a chat client. They depend on :class:`TextReasoner`, whose
implementations live in the framework layer at runtime and are replaced by a
scripted double in tests.

The *request* they carry - instructions, task, and untrusted context separated by
construction - now lives in ``ygo74-agent-runtime``: keeping trusted instructions
apart from third-party material is the same problem for every agent. It is
re-exported here so a capability has one import rather than two.

What stays is the port itself. Which model answers, and through which framework,
is this laboratory's question - it is the whole subject of the comparison - and
not the library's business.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel
from ygo74.agent_runtime.domains.security.prompt_envelope import ReasoningRequest, UntrustedSection

__all__ = ["ReasoningOutputT", "ReasoningRequest", "TextReasoner", "UntrustedSection"]

ReasoningOutputT = TypeVar("ReasoningOutputT", bound=BaseModel)


@runtime_checkable
class TextReasoner(Protocol):
    """Produces a typed result from a reasoning request."""

    async def reason(
        self,
        request: ReasoningRequest,
        response_model: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        """Return a validated instance of ``response_model``.

        Raises:
            ReasoningUnavailableError: the backend could not be reached.
            ReasoningOutputError: the answer could not be validated.
        """
        ...
