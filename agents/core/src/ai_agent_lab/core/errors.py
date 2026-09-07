"""Base exceptions of the domain layer."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error that carries domain meaning."""


class DomainValidationError(DomainError):
    """Raised when domain data violates a business invariant."""
