"""Security floor of the mail MCP tools.

Delivering a message cannot be taken back, so no configuration may present it as
anything but a high-risk operation requiring an explicit confirmation.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.security.floor import OperationFloor, SecurityFloor
from ygo74.agent_runtime.domains.security.operations import RiskLevel

from ai_agent_lab.mail.catalog import MailToolName


class MailSecurityFloor:
    """Builds the floor the mail configuration must respect."""

    def build(self) -> SecurityFloor:
        """Return the floors imposed on the mail operations."""
        return SecurityFloor(
            (
                OperationFloor(
                    tool_name=MailToolName.SEND_MAIL.value,
                    minimum_risk=RiskLevel.HIGH,
                    confirmation_always_required=True,
                ),
            )
        )
