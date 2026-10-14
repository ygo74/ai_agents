"""Compatibility imports for the runtime's reusable native approval translator."""

from ygo74.agent_runtime.integrations.agentframework.approval import (
    APPROVAL_REQUEST_TYPE,
    MafApprovalTranslator,
    PendingToolApproval,
)

__all__ = ["APPROVAL_REQUEST_TYPE", "MafApprovalTranslator", "PendingToolApproval"]
