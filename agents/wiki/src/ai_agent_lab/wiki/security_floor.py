"""Security floor of the wiki MCP tools.

Two operations may never be presented as anything milder than they are, whatever
a delivered configuration says.

``update_page`` overwrites text people wrote. The previous revision survives in
the page history, so it is not destruction in the strict sense - but restoring it
is a manual act outside this agent, and everyone watching the space is notified
of the change in the meantime. An agent that silently rewrote a team's page would
be the single most damaging thing this system could do.

``delete_page`` takes a page out of the wiki. Its children stop being reachable
through it and every link pointing at it breaks, and nothing anywhere records
which pages those were.

``create_page`` and ``add_comment`` are deliberately *not* floored. They add
without removing, and a deployment that wants an agent to draft pages
unattended should be allowed to decide that. The floor holds the line at
operations that damage what already exists.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.security.floor import OperationFloor, SecurityFloor
from ygo74.agent_runtime.domains.security.operations import RiskLevel

from ai_agent_lab.wiki.catalog import WikiToolName


class WikiSecurityFloor:
    """Builds the floor the wiki configuration must respect."""

    def build(self) -> SecurityFloor:
        """Return the floors imposed on the wiki operations."""
        return SecurityFloor(
            (
                OperationFloor(
                    tool_name=WikiToolName.UPDATE_PAGE.value,
                    minimum_risk=RiskLevel.HIGH,
                    confirmation_always_required=True,
                ),
                OperationFloor(
                    tool_name=WikiToolName.DELETE_PAGE.value,
                    minimum_risk=RiskLevel.HIGH,
                    confirmation_always_required=True,
                ),
            )
        )
