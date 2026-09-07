"""Security errors of the domain layer."""

from __future__ import annotations

from ai_agent_lab.core.errors import DomainError


class SecurityError(DomainError):
    """Base class for security-related domain errors."""


class AuthorizationError(SecurityError):
    """Raised when a user context lacks the permission required by an operation."""

    def __init__(self, user_id: str, required_permission: str) -> None:
        super().__init__(f"user {user_id!r} is not allowed to perform {required_permission!r}")
        self.user_id = user_id
        self.required_permission = required_permission


class ConfirmationRequiredError(SecurityError):
    """Raised when a gated operation is attempted without an approval decision."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"operation {tool_name!r} requires an explicit user confirmation")
        self.tool_name = tool_name


class ConfirmationRejectedError(SecurityError):
    """Raised when the user explicitly declined a gated operation."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"operation {tool_name!r} was declined by the user")
        self.tool_name = tool_name


class ConfirmationMismatchError(SecurityError):
    """Raised when an approval decision does not match the pending request.

    This blocks replaying a confirmation obtained for another operation.
    """

    def __init__(self, expected_request_id: str, received_request_id: str) -> None:
        super().__init__(
            f"confirmation {received_request_id!r} does not match pending request {expected_request_id!r}"
        )
        self.expected_request_id = expected_request_id
        self.received_request_id = received_request_id
