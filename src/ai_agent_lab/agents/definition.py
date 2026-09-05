"""Framework-independent description of an agent.

An agent definition is data: an identity, instructions and the list of
capabilities it may expose. It contains no business logic and no framework
type, which is what allows the same Mail Agent to be run by Microsoft Agent
Framework today and by LangChain or CrewAI tomorrow without touching a skill.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.domain.security.operations import ToolOperationDescriptor

SkillInvocation = Callable[[BaseModel, UserContext], Awaitable[BaseModel]]


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    """One capability an agent may expose to a model.

    Attributes:
        tool_name: Name advertised to the model.
        description: What the capability does and what it does not do. The model
            selects tools from this text, so it is part of the contract.
        input_model: Schema the model must fill in.
        operation: Security metadata driving the confirmation policy.
        invoke: Coroutine executing the capability.
    """

    tool_name: str
    description: str
    input_model: type[BaseModel]
    operation: ToolOperationDescriptor
    invoke: SkillInvocation

    def __post_init__(self) -> None:
        """Reject a descriptor whose declared name does not match its operation."""
        if self.tool_name != self.operation.tool_name:
            raise ValueError(
                f"skill {self.tool_name!r} declares the operation of {self.operation.tool_name!r}"
            )


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Identity, instructions and capabilities of an agent."""

    name: str
    description: str
    instructions: str
    skills: Sequence[SkillDescriptor]

    def skill(self, tool_name: str) -> SkillDescriptor:
        """Return one capability by name."""
        for descriptor in self.skills:
            if descriptor.tool_name == tool_name:
                return descriptor
        raise KeyError(f"agent {self.name!r} exposes no skill named {tool_name!r}")

    def write_skills(self) -> tuple[SkillDescriptor, ...]:
        """Capabilities that change external state.

        Whether such a capability is actually gated depends on the confirmation
        policy evaluated for a given user, which lives outside the definition.
        """
        return tuple(descriptor for descriptor in self.skills if descriptor.operation.is_write)
