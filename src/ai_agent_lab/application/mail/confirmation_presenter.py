"""Presentation of a suspended tool call as a confirmation request.

The agent framework suspends a gated call and reports the raw arguments the
model proposed. Those arguments are not enough for an informed decision: a
draft reference tells the user nothing about who would receive what.

This presenter resolves them into the same confirmation request the skills
build, so the user sees recipients, subject and body before approving.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ai_agent_lab.application.mail.skills_factory import MailSkills
from ai_agent_lab.domain.errors import DomainError
from ai_agent_lab.domain.mail.ports import DraftStore
from ai_agent_lab.domain.security.confirmation import ConfirmationRequest
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.mcp.mail.catalog import MailToolName

_HOUSEKEEPING = frozenset(
    {
        MailToolName.MARK_READ,
        MailToolName.ARCHIVE_MAIL,
        MailToolName.APPLY_LABEL,
        MailToolName.REMOVE_LABEL,
    }
)


class UnknownGatedToolError(DomainError):
    """Raised when a suspended tool call cannot be described to the user."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"no confirmation can be presented for the capability {tool_name!r}")
        self.tool_name = tool_name


class MailConfirmationPresenter:
    """Turns a pending tool approval into something a human can judge."""

    def __init__(self, skills: MailSkills, draft_store: DraftStore) -> None:
        self._skills = skills
        self._draft_store = draft_store

    def present(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        user: UserContext,
    ) -> ConfirmationRequest:
        """Build the confirmation request shown for a suspended tool call.

        Raises:
            UnknownGatedToolError: the capability cannot be described. Failing
                here is deliberate: approving an operation nobody can explain
                would be worse than interrupting the conversation.
        """
        tool = self._tool_for(tool_name)
        if tool is MailToolName.SEND_MAIL:
            return self._present_send(arguments, user)
        if tool in _HOUSEKEEPING:
            return self._present_housekeeping(tool, arguments)
        raise UnknownGatedToolError(tool_name)

    def _present_send(self, arguments: Mapping[str, Any], user: UserContext) -> ConfirmationRequest:
        """Resolve the draft so the user sees what would actually be delivered."""
        reference = str(arguments.get("draft_reference", ""))
        draft = self._draft_store.get(reference, user)
        return self._skills.send.build_confirmation_request(draft)

    def _present_housekeeping(self, tool: MailToolName, arguments: Mapping[str, Any]) -> ConfirmationRequest:
        """Describe a mailbox change in the user's terms."""
        is_read = arguments.get("is_read")
        return self._skills.management.build_confirmation_request(
            tool,
            str(arguments.get("message_id", "")),
            label_id=self._optional_str(arguments.get("label_id")),
            is_read=is_read if isinstance(is_read, bool) else None,
        )

    @staticmethod
    def _tool_for(tool_name: str) -> MailToolName | None:
        """Map a tool name onto the catalogue, if it belongs to it."""
        try:
            return MailToolName(tool_name)
        except ValueError:
            return None

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        """Return a string argument when present."""
        return None if value is None else str(value)
