"""Typed description of a skill and of an agent.

A manifest is the resolved, validated form of what configuration declares:
identity, description, security posture and, for a skill driven by a language
model, its prompt. It carries no file format, no framework type and no callable,
so the same manifests drive Microsoft Agent Framework today and another
orchestrator tomorrow.

What a manifest deliberately does not carry: the deterministic logic of a skill
and the schema of its arguments. Both are contracts expressed in code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_lab.core.security.operations import ToolOperationDescriptor


class SkillManifest(BaseModel):
    """What configuration declares about one capability.

    Attributes:
        tool_name: Name advertised to the model.
        implementation: Key binding the manifest to the code that runs it.
        description: What the capability does and does not do. The model selects
            tools from this text, so it is part of the contract.
        operation: Security metadata driving the confirmation policy.
        mcp_tools: Logical MCP tools the capability is allowed to use.
        prompt: Reasoning instructions. Empty for a deterministic capability.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(min_length=1)
    implementation: str = Field(min_length=1)
    description: str = Field(min_length=1)
    operation: ToolOperationDescriptor
    mcp_tools: tuple[str, ...] = ()
    prompt: str = ""

    @model_validator(mode="after")
    def _check_operation_matches(self) -> SkillManifest:
        """Reject a manifest declaring the security posture of another tool."""
        if self.operation.tool_name != self.tool_name:
            raise ValueError(
                f"skill {self.tool_name!r} declares the operation of {self.operation.tool_name!r}"
            )
        return self

    @property
    def is_reasoning(self) -> bool:
        """Whether the capability drives a language model."""
        return bool(self.prompt)


class AgentManifest(BaseModel):
    """What configuration declares about one agent.

    ``skills`` lists the capabilities the agent exposes, in the order they are
    offered to the model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    skills: tuple[SkillManifest, ...] = ()

    def skill(self, tool_name: str) -> SkillManifest:
        """Return one declared capability by name."""
        for manifest in self.skills:
            if manifest.tool_name == tool_name:
                return manifest
        raise KeyError(f"agent {self.name!r} declares no skill named {tool_name!r}")
