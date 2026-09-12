"""Exposure of the repository skills as Microsoft Agent Framework tools."""

from __future__ import annotations

import logging
from typing import Any, Literal

from agent_framework import FunctionTool
from ygo74.agent_runtime.domains.contracts.capability_registry import ResultRenderer, SkillDescriptor, SkillRegistry
from ygo74.agent_runtime.domains.security.security_errors import SecurityError
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.confirmation import ConfirmationPolicy

ApprovalMode = Literal["always_require", "never_require"]

_ALWAYS_REQUIRE: ApprovalMode = "always_require"
_NEVER_REQUIRE: ApprovalMode = "never_require"

_logger = logging.getLogger(__name__)


class SkillToolAdapter:
    """Turns skill descriptors into framework tools.

    The approval mode of each tool comes from the deterministic confirmation
    policy, evaluated for the user the agent is acting for. The language model
    is never consulted about it.
    """

    def __init__(self, renderer: ResultRenderer, policy: ConfirmationPolicy) -> None:
        self._renderer = renderer
        self._policy = policy

    def to_tools(self, definition: SkillRegistry, user: UserContext) -> tuple[FunctionTool, ...]:
        """Expose every capability of an agent definition as a framework tool."""
        return tuple(self.to_tool(descriptor, user) for descriptor in definition.skills)

    def to_tool(self, descriptor: SkillDescriptor, user: UserContext) -> FunctionTool:
        """Expose one capability as a framework tool."""

        async def invoke(**arguments: Any) -> str:
            return await self._run(descriptor, user, arguments)

        return FunctionTool(
            name=descriptor.tool_name,
            description=descriptor.description,
            input_model=descriptor.input_model,
            approval_mode=self._approval_mode(descriptor, user),
            func=invoke,
        )

    def _approval_mode(self, descriptor: SkillDescriptor, user: UserContext) -> ApprovalMode:
        """Map the confirmation policy onto the framework approval mode."""
        if self._policy.requires_confirmation(descriptor.operation, user):
            return _ALWAYS_REQUIRE
        return _NEVER_REQUIRE

    async def _run(
        self,
        descriptor: SkillDescriptor,
        user: UserContext,
        arguments: dict[str, Any],
    ) -> str:
        """Validate the arguments, run the skill and render the result."""
        payload = descriptor.input_model.model_validate(arguments)
        try:
            result = await descriptor.invoke(payload, user)
        except (DomainError, SecurityError) as error:
            return self._render_refusal(descriptor, error)
        return self._renderer.render(result)

    @staticmethod
    def _render_refusal(descriptor: SkillDescriptor, error: DomainError | SecurityError) -> str:
        """Report a domain failure to the model without leaking internals.

        The model needs to know the operation did not happen and why, so it can
        tell the user instead of assuming success.

        It is also logged here, and that matters more than it looks. Returning
        this text is a normal return as far as the framework is concerned, so
        its own log says "Function apply_label succeeded". An operator watching
        the console would otherwise read a column of successes and wonder why
        nothing changed in the mailbox.
        """
        _logger.warning(
            "capability %s did not run: %s: %s",
            descriptor.tool_name,
            type(error).__name__,
            error,
        )
        return (
            f'The capability "{descriptor.tool_name}" did not run.\n'
            f"Reason ({type(error).__name__}): {error}\n"
            "Report this to the user. Do not retry with different arguments unless the user asks."
        )
