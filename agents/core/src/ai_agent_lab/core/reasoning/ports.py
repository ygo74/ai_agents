"""Port through which skills obtain language-model reasoning.

Skills must stay usable with Microsoft Agent Framework, LangChain or CrewAI, so
they never depend on a chat client. They depend on :class:`TextReasoner`, whose
implementations live in the framework layer at runtime and are replaced by a
scripted double in tests.

A reasoning request separates trusted instructions from untrusted material by
construction: the task comes from the application, the context comes from an
MCP server and is carried as :class:`UntrustedText`.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.core.security.untrusted import UntrustedText

ReasoningOutputT = TypeVar("ReasoningOutputT", bound=BaseModel)


class UntrustedSection(BaseModel):
    """A labelled block of third-party content offered to the model as data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1)
    content: UntrustedText


class ReasoningRequest(BaseModel):
    """A reasoning task with its untrusted context.

    Attributes:
        instructions: Trusted role and rules given to the model.
        task: Trusted description of what must be produced.
        context: Untrusted material the answer must be grounded in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    instructions: str = Field(min_length=1)
    task: str = Field(min_length=1)
    context: tuple[UntrustedSection, ...] = ()


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
