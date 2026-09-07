"""Registry of the capabilities an agent exposes.

This is deliberately not an abstraction over an agent. It is the list of
capabilities an orchestrator needs in order to build its own tools: a name, a
description, an argument schema, the security posture and the coroutine that
runs the capability.

Microsoft Agent Framework, LangChain and CrewAI each build their tools from this
same registry, which is what keeps the skills from being ported three times.
Building the agent itself is left to each framework, in its own documented way.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from ai_agent_lab.core.manifests import SkillManifest
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.operations import ToolOperationDescriptor

SkillInvocation = Callable[[BaseModel, UserContext], Awaitable[BaseModel]]


class ResultRenderer(Protocol):
    """Turns the typed result of a capability into the text a model reads.

    Each agent renders its own results: what a mailbox search should look like in
    a conversation is a mail decision, not a framework one. A framework adapter
    asks for this and nothing more, which is what keeps it usable by the next
    agent without a change.
    """

    def render(self, result: BaseModel | Sequence[BaseModel]) -> str:
        """Render a capability result as text."""
        ...


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    """One capability, ready to be turned into a tool.

    Attributes:
        tool_name: Name advertised to the model.
        description: What the capability does and what it does not do. The model
            selects tools from this text, so it is part of the contract.
        input_model: Schema the model must fill in. A contract, hence code.
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

    @classmethod
    def from_manifest(
        cls,
        manifest: SkillManifest,
        input_model: type[BaseModel],
        invoke: SkillInvocation,
    ) -> SkillDescriptor:
        """Bind a delivered manifest to the code that runs it."""
        return cls(
            tool_name=manifest.tool_name,
            description=manifest.description,
            input_model=input_model,
            operation=manifest.operation,
            invoke=invoke,
        )


@dataclass(frozen=True, slots=True)
class SkillRegistry:
    """The capabilities available to one agent, in the order they are offered."""

    skills: Sequence[SkillDescriptor]

    def skill(self, tool_name: str) -> SkillDescriptor:
        """Return one capability by name."""
        for descriptor in self.skills:
            if descriptor.tool_name == tool_name:
                return descriptor
        raise KeyError(f"no skill named {tool_name!r} is registered")

    def write_skills(self) -> tuple[SkillDescriptor, ...]:
        """Capabilities that change external state.

        Whether such a capability is actually gated depends on the confirmation
        policy evaluated for a given user, which lives outside the registry.
        """
        return tuple(descriptor for descriptor in self.skills if descriptor.operation.is_write)
