"""Small native MAF composition for a framework-neutral registered capability set."""

from agent_framework import Agent, SupportsChatGetResponse
from ygo74.agent_runtime.domains.contracts.capability_registry import ResultRenderer, SkillRegistry
from ygo74.agent_runtime.domains.humanapproval.confirmation import ConfirmationPolicy
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.maf.tool_adapter import SkillToolAdapter


def create_registered_agent(
    *,
    client: SupportsChatGetResponse,
    name: str,
    instructions: str,
    registry: SkillRegistry,
    renderer: ResultRenderer,
    policy: ConfirmationPolicy,
    user: UserContext,
) -> Agent:
    """Compose native framework behavior from trusted instructions and injected registry."""
    tools = SkillToolAdapter(renderer, policy).to_tools(registry, user)
    return Agent(client=client, name=name, instructions=instructions, tools=list(tools))
