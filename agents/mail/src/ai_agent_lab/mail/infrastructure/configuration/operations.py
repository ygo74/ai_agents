"""Translation of the delivered manifest into application operation metadata."""

from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.security.operations import ToolOperationDescriptor

from ai_agent_lab.mail.application.operations import MailToolCatalog
from ai_agent_lab.mail.domain.operation_names import MailToolName


class DeliveredMailOperations:
    """Read the delivered posture, using coded defaults for absent operations."""

    def __init__(self, manifest: AgentManifest, fallback: MailToolCatalog | None = None) -> None:
        self._manifest = manifest
        self._fallback = fallback or MailToolCatalog()
        self._declared = {skill.tool_name: skill.operation for skill in manifest.skills}

    def descriptor(self, name: MailToolName) -> ToolOperationDescriptor:
        """Return the security metadata this deployment declares."""
        declared = self._declared.get(name.value)
        return declared if declared is not None else self._fallback.descriptor(name)
