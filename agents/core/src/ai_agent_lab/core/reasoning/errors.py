"""Errors of the reasoning layer."""

from __future__ import annotations

from ai_agent_lab.core.errors import DomainError


class ReasoningError(DomainError):
    """Base class for failures of a language-model backed reasoner."""


class ReasoningUnavailableError(ReasoningError):
    """Raised when the reasoning backend cannot be reached."""


class ReasoningOutputError(ReasoningError):
    """Raised when the reasoner returned something the domain cannot use."""
