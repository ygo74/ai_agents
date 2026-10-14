"""Failures of Mail deployment configuration."""

from ai_agent_lab.mail.application.errors import MailToolError


class MailAgentConfigurationError(MailToolError):
    """Refuse to assemble an agent from an unusable configuration."""
