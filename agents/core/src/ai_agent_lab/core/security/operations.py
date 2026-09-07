"""Classification of the operations an agent may perform.

Every capability exposed to a model declares what it does to the outside world.
That declaration is data, decided in code, and is the input of the confirmation
policy. The model never contributes to it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.core.security.permissions import Permission


class OperationType(StrEnum):
    """Whether an operation observes or modifies external state."""

    READ = "READ"
    WRITE = "WRITE"


class RiskLevel(StrEnum):
    """How damaging an unintended execution would be."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ToolOperationDescriptor(BaseModel):
    """Security metadata attached to one exposed capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(min_length=1)
    operation_type: OperationType
    risk_level: RiskLevel
    required_permission: Permission
    confirmation_required_by_default: bool

    @property
    def is_write(self) -> bool:
        """Whether the operation modifies external state."""
        return self.operation_type is OperationType.WRITE
