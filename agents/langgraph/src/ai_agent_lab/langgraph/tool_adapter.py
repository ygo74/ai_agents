"""Exposure of the repository skills as LangChain tools.

The registry is the shared source: the same :class:`SkillDescriptor` that the
Microsoft Agent Framework adapter turns into a ``FunctionTool`` becomes a
``StructuredTool`` here. Nothing about a skill is written twice, which is what
makes a comparison between the two frameworks measure the frameworks rather than
two independent implementations.

Unlike the MAF adapter, this one does *not* carry the approval mode: LangChain
declares which tools are gated on the middleware rather than on the tool. That
decision still comes from the same deterministic policy - see
:mod:`ai_agent_lab.langgraph.approval`.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.registry import ResultRenderer, SkillDescriptor, SkillRegistry
from ai_agent_lab.core.security.context import UserContext

_logger = logging.getLogger(__name__)


class SkillToolAdapter:
    """Turns skill descriptors into LangChain tools."""

    def __init__(self, renderer: ResultRenderer) -> None:
        self._renderer = renderer

    def to_tools(self, definition: SkillRegistry, user: UserContext) -> tuple[StructuredTool, ...]:
        """Expose every capability of an agent definition as a framework tool."""
        _logger.info(
            "Adapting %d skills to LangChain StructuredTools for user=%s",
            len(definition.skills),
            user.user_id,
        )
        tools = tuple(self.to_tool(descriptor, user) for descriptor in definition.skills)
        _logger.info("Adapted %d skills to LangChain StructuredTools successfully", len(tools))
        _logger.debug("Adapted tools: %s", [t.name for t in tools])
        return tools

    def to_tool(self, descriptor: SkillDescriptor, user: UserContext) -> StructuredTool:
        """Expose one capability as a framework tool."""
        _logger.debug("Adapting skill '%s' (input_model=%s)", descriptor.tool_name, descriptor.input_model.__name__)

        async def invoke(**arguments: Any) -> str:
            return await self._run(descriptor, user, arguments)

        return StructuredTool.from_function(
            coroutine=invoke,
            name=descriptor.tool_name,
            description=descriptor.description,
            args_schema=descriptor.input_model,
        )

    async def _run(
        self,
        descriptor: SkillDescriptor,
        user: UserContext,
        arguments: dict[str, Any],
    ) -> str:
        """Validate the arguments, run the skill and render the result."""
        _logger.info("Executing capability '%s' for user=%s", descriptor.tool_name, user.user_id)
        _logger.debug("Capability '%s' input arguments: %s", descriptor.tool_name, arguments)
        payload = descriptor.input_model.model_validate(arguments)
        try:
            result = await descriptor.invoke(payload, user)
        except DomainError as error:
            return self._render_refusal(descriptor, error)
        rendered = self._renderer.render(result)
        _logger.info("Capability '%s' succeeded (output_length=%d)", descriptor.tool_name, len(rendered))
        _logger.debug("Capability '%s' rendered output: %s", descriptor.tool_name, rendered)
        return rendered

    @staticmethod
    def _render_refusal(descriptor: SkillDescriptor, error: DomainError) -> str:
        """Report a domain failure to the model without leaking internals.

        The model needs to know the operation did not happen and why, so it can
        tell the user instead of assuming success.

        It is also logged here, and that matters more than it looks. Returning
        this text is a normal return as far as the framework is concerned, so its
        own trace records a successful tool call. An operator watching the console
        would otherwise read a column of successes and wonder why nothing changed.
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
