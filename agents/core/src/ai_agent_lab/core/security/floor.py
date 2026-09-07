"""Security posture a configuration may not go below.

Descriptions, prompts and confirmation defaults are configuration. The fact that
delivering an email is irreversible is not: it is a property of the operation
itself, and it stays in code.

A configuration that would weaken such an operation is refused at load time
rather than silently corrected. A security control that repairs itself in
silence teaches nobody that the configuration was wrong.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ai_agent_lab.core.security.errors import SecurityError
from ai_agent_lab.core.security.operations import RiskLevel, ToolOperationDescriptor

_SEVERITY = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


class SecurityFloorViolationError(SecurityError):
    """Raised when a configuration declares less protection than the code requires."""

    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(f"configuration of {tool_name!r} is refused: {reason}")
        self.tool_name = tool_name


@dataclass(frozen=True, slots=True)
class OperationFloor:
    """The weakest posture an operation is allowed to be configured with."""

    tool_name: str
    minimum_risk: RiskLevel
    confirmation_always_required: bool = True


class SecurityFloor:
    """Checks declared operations against the floors the code imposes."""

    def __init__(self, floors: Iterable[OperationFloor]) -> None:
        self._by_tool = {floor.tool_name: floor for floor in floors}

    def confirmation_is_mandatory(self, tool_name: str) -> bool:
        """Whether no configuration may remove the confirmation of an operation.

        This is the single answer to "may a deployment, or a person, decide
        otherwise". Asking the risk level instead would conflate how much an
        operation costs with who is allowed to choose.
        """
        floor = self._by_tool.get(tool_name)
        return floor is not None and floor.confirmation_always_required

    def enforce(self, descriptor: ToolOperationDescriptor) -> None:
        """Refuse a descriptor that sits below the floor of its operation."""
        floor = self._by_tool.get(descriptor.tool_name)
        if floor is None:
            return
        self._check_risk(descriptor, floor)
        self._check_confirmation(descriptor, floor)

    @staticmethod
    def _check_risk(descriptor: ToolOperationDescriptor, floor: OperationFloor) -> None:
        """Refuse a risk level lower than the floor."""
        if _SEVERITY[descriptor.risk_level] >= _SEVERITY[floor.minimum_risk]:
            return
        raise SecurityFloorViolationError(
            descriptor.tool_name,
            f"risk {descriptor.risk_level.value} is below the required {floor.minimum_risk.value}",
        )

    @staticmethod
    def _check_confirmation(descriptor: ToolOperationDescriptor, floor: OperationFloor) -> None:
        """Refuse a configuration disarming a mandatory confirmation."""
        if not floor.confirmation_always_required or descriptor.confirmation_required_by_default:
            return
        raise SecurityFloorViolationError(
            descriptor.tool_name,
            "this operation always requires a confirmation",
        )
