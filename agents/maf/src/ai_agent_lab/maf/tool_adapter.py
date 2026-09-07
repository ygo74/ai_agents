"""Exposure of the repository skills as Microsoft Agent Framework tools."""

from __future__ import annotations

from typing import Any, Literal

from agent_framework import FunctionTool

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.registry import ResultRenderer, SkillDescriptor, SkillRegistry
from ai_agent_lab.core.security.confirmation import ConfirmationPolicy
from ai_agent_lab.core.security.context import UserContext

ApprovalMode = Literal["always_require", "never_require"]

_ALWAYS_REQUIRE: ApprovalMode = "always_require"
_NEVER_REQUIRE: ApprovalMode = "never_require"


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
        except DomainError as error:
            return self._render_refusal(descriptor, error)
        return self._renderer.render(result)

    @staticmethod
    def _render_refusal(descriptor: SkillDescriptor, error: DomainError) -> str:
        """Report a domain failure to the model without leaking internals.

        The model needs to know the operation did not happen and why, so it can
        tell the user instead of assuming success.
        """
        return (
            f'The capability "{descriptor.tool_name}" did not run.\n'
            f"Reason ({type(error).__name__}): {error}\n"
            "Report this to the user. Do not retry with different arguments unless the user asks."
        )
