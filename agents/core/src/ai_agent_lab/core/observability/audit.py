"""Audit trail implementations."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ai_agent_lab.domain.security.audit import AuditRecord, AuditTrail

_LOGGER = logging.getLogger("ai_agent_lab.audit")


class InMemoryAuditTrail:
    """Keeps audit records in memory, for demos, scenarios and assertions."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    @property
    def records(self) -> Sequence[AuditRecord]:
        """Every record captured so far."""
        return tuple(self._records)

    def record(self, entry: AuditRecord) -> None:
        """Append one audit record."""
        self._records.append(entry)

    def records_for(self, tool_name: str) -> tuple[AuditRecord, ...]:
        """Records concerning one tool."""
        return tuple(entry for entry in self._records if entry.tool_name == tool_name)

    def clear(self) -> None:
        """Drop every captured record."""
        self._records.clear()


class LoggingAuditTrail:
    """Writes audit records through the standard logging facility.

    Records carry identifiers and outcomes only, so this is safe to enable in
    any environment: no message content can reach the logs through it.
    """

    def __init__(self, delegate: AuditTrail | None = None) -> None:
        self._delegate = delegate

    def record(self, entry: AuditRecord) -> None:
        """Log one audit record and forward it to the delegate, if any."""
        _LOGGER.info(
            "audit tool=%s operation=%s risk=%s outcome=%s user=%s session=%s target=%s error=%s",
            entry.tool_name,
            entry.operation_type.value,
            entry.risk_level.value,
            entry.outcome.value,
            entry.user_id,
            entry.session_id,
            entry.target_id,
            entry.error_type,
        )
        if self._delegate is not None:
            self._delegate.record(entry)
