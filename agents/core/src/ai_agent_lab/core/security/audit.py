"""Audit trail of the operations an agent performs.

Every attempt to change external state is recorded, whether it succeeded, was
declined by the user or failed. The record is deliberately made of identifiers
and outcomes only: no message body, no subject, no recipient list, no
credential ever reaches the audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.core.security.operations import OperationType, RiskLevel


class AuditOutcome(StrEnum):
    """How an attempted operation ended."""

    EXECUTED = "EXECUTED"
    DECLINED = "DECLINED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class AuditRecord(BaseModel):
    """One entry of the audit trail."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(min_length=1)
    operation_type: OperationType
    risk_level: RiskLevel
    outcome: AuditOutcome
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    target_id: str | None = None
    confirmation_request_id: str | None = None
    error_type: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class AuditTrail(Protocol):
    """Destination of the audit records."""

    def record(self, entry: AuditRecord) -> None:
        """Persist one audit record."""
        ...
