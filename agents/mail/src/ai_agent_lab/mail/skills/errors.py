"""Errors raised by the mail skills."""

from __future__ import annotations

from ai_agent_lab.domain.errors import DomainError


class MailSkillError(DomainError):
    """Base class for failures of a mail skill."""


class EmptyMailSelectionError(MailSkillError):
    """Raised when a skill was asked to work on no message at all."""

    def __init__(self, skill_name: str) -> None:
        super().__init__(f"{skill_name} requires at least one message to work on")
        self.skill_name = skill_name


class UngroundedMailResultError(MailSkillError):
    """Raised when a reasoner referenced a message that was not part of the context.

    Accepting such a result would let untrusted content fabricate a source, so
    the skill rejects it instead of degrading it silently.
    """

    def __init__(self, message_id: str) -> None:
        super().__init__(f"result references message {message_id!r} which was not part of the analysed context")
        self.message_id = message_id
