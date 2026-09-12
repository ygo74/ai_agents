"""Security errors that are specific to this laboratory.

The base class, and the refusal raised when a caller lacks a permission, now live
in ``ygo74.agent_runtime.domains.security.security_errors``: they describe a model
that no longer belongs to one application. The refusal is named
``PermissionDeniedError`` there, because the runtime already had an
``AuthorizationError`` meaning something else - what an HTTP surface does with a
request a handler denied, which it maps to a 403.

What stays here is the confirmation vocabulary. It is the language of the
human-approval mechanism, which is not yet part of the runtime, and it is re-based
on the runtime's :class:`SecurityError` so that one ``except`` still catches every
security failure of an agent.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.security.security_errors import SecurityError


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
        super().__init__(f"confirmation {received_request_id!r} does not match pending request {expected_request_id!r}")
        self.expected_request_id = expected_request_id
        self.received_request_id = received_request_id
