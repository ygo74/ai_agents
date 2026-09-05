"""Assembly of the Mail Agent definition."""

from __future__ import annotations

from ai_agent_lab.agents.definition import AgentDefinition
from ai_agent_lab.agents.mail.instructions import (
    MAIL_AGENT_DESCRIPTION,
    MAIL_AGENT_INSTRUCTIONS,
    MAIL_AGENT_NAME,
)
from ai_agent_lab.agents.mail.read_capabilities import MailReadCapabilities
from ai_agent_lab.agents.mail.write_capabilities import MailWriteCapabilities


class MailAgentDefinitionFactory:
    """Builds the framework-independent definition of the Mail Agent.

    The factory owns nothing but the assembly: identity, instructions and the
    ordered list of capabilities. Everything it composes was injected, so the
    same definition can be handed to any framework adapter.
    """

    def __init__(
        self,
        read_capabilities: MailReadCapabilities,
        write_capabilities: MailWriteCapabilities,
    ) -> None:
        self._read_capabilities = read_capabilities
        self._write_capabilities = write_capabilities

    def build(self) -> AgentDefinition:
        """Return the definition of the Mail Agent."""
        return AgentDefinition(
            name=MAIL_AGENT_NAME,
            description=MAIL_AGENT_DESCRIPTION,
            instructions=MAIL_AGENT_INSTRUCTIONS,
            skills=(*self._read_capabilities.descriptors(), *self._write_capabilities.descriptors()),
        )
