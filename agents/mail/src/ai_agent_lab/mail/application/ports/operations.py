"""Application port for the security posture of mailbox operations."""

from typing import Protocol, runtime_checkable

from ygo74.agent_runtime.domains.security.operations import ToolOperationDescriptor

from ai_agent_lab.mail.domain.operation_names import MailToolName


@runtime_checkable
class MailOperations(Protocol):
    """One posture shared by skill gates and framework tool approval."""

    def descriptor(self, name: MailToolName) -> ToolOperationDescriptor:
        """Return the active security metadata of an operation."""
        ...
