"""Execution of the mail operations that change external state.

The logic moved to ``ygo74-agent-runtime``: permission check, confirmation policy
and audit record are the same three steps for every agent, and the Wiki Agent had
grown its own copy of them. A copy per agent is one copy away from one of them
being weaker, and the divergence would be invisible because both would still pass
their own tests.

What stays here is the binding: which enumeration names this agent's tools, and
where their posture is read from. :class:`MailOperations` already satisfies the
library's ``OperationCatalogue`` protocol, so the alias below is the whole of it
and no skill call site changes.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.humanapproval.gated_operations import GatedOperationRunner

from ai_agent_lab.mail.catalog import MailToolName

# The runner this agent's skills are given. It must read the same posture the
# framework adapter reads: consulting two sources would let a capability be both
# never asked about and always refused.
GatedMailOperationRunner = GatedOperationRunner[MailToolName]

__all__ = ["GatedMailOperationRunner"]
