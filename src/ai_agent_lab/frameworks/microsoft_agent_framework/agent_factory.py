"""Construction of the Mail Agent on Microsoft Agent Framework."""

from __future__ import annotations

from agent_framework import Agent, FunctionTool, SupportsChatGetResponse, ToolApprovalMiddleware

from ai_agent_lab.agents.definition import AgentDefinition
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.frameworks.microsoft_agent_framework.tool_adapter import SkillToolAdapter


class MafAgentFactory:
    """Assembles a framework agent from a framework-independent definition.

    The factory only wires: identity and instructions come from the definition,
    tools from the adapter, and the approval middleware from the framework. No
    business rule is introduced here.
    """

    def __init__(self, client: SupportsChatGetResponse, tool_adapter: SkillToolAdapter) -> None:
        self._client = client
        self._tool_adapter = tool_adapter

    def build(self, definition: AgentDefinition, user: UserContext) -> Agent:
        """Build the agent acting on behalf of the given user."""
        return Agent(
            self._client,
            definition.instructions,
            id=definition.name,
            name=definition.name,
            description=definition.description,
            tools=list(self.build_tools(definition, user)),
            middleware=[ToolApprovalMiddleware()],
        )

    def build_tools(self, definition: AgentDefinition, user: UserContext) -> tuple[FunctionTool, ...]:
        """Expose the capabilities of the definition as framework tools."""
        return self._tool_adapter.to_tools(definition, user)
