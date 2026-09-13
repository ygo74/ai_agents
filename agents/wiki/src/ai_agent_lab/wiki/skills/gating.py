"""Execution of the wiki operations that change external state.

The logic moved to ``ygo74-agent-runtime``, where it is written once for every
agent. The two agents run on different frameworks; the guarantee they owe a user
does not depend on which, and it no longer depends on two copies staying in step
either.

What stays here is the binding: which enumeration names this agent's tools, and
where their posture is read from. :class:`WikiOperations` already satisfies the
library's ``OperationCatalogue`` protocol, so the alias below is the whole of it
and no skill call site changes.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.humanapproval.gated_operations import GatedOperationRunner

from ai_agent_lab.wiki.catalog import WikiToolName

# The runner this agent's skills are given. It must read the same posture the
# framework adapter reads: consulting two sources would let a capability be both
# never asked about and always refused, and the model would report that the wiki
# had refused.
GatedWikiOperationRunner = GatedOperationRunner[WikiToolName]

__all__ = ["GatedWikiOperationRunner"]
