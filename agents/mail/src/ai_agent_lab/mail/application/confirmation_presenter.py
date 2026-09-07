"""Presentation of a suspended tool call as a confirmation request.

The agent framework suspends a gated call and reports the raw arguments the
model proposed. Those arguments are not enough for an informed decision: a
draft reference tells the user nothing about who would receive what, and a
message identifier tells them nothing about which message it is.

This presenter resolves them into the same confirmation request the skills
build, so the user sees recipients, subject, sender and label names before
approving.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.confirmation import ConfirmationRequest
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.application.confirmation_subjects import ConfirmationSubjectResolver
from ai_agent_lab.mail.application.skills_factory import MailSkills
from ai_agent_lab.mail.capabilities.write_capabilities import housekeeping_target
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.domain.ports import DraftStore

_HOUSEKEEPING = frozenset(
    {
        MailToolName.MARK_READ,
        MailToolName.ARCHIVE_MAIL,
        MailToolName.APPLY_LABEL,
        MailToolName.REMOVE_LABEL,
    }
)

_LABEL_LIFECYCLE = frozenset({MailToolName.CREATE_LABEL, MailToolName.DELETE_LABEL})


class UnknownGatedToolError(DomainError):
    """Raised when a suspended tool call cannot be described to the user."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"no confirmation can be presented for the capability {tool_name!r}")
        self.tool_name = tool_name


class MailConfirmationPresenter:
    """Turns a pending tool approval into something a human can judge."""

    def __init__(
        self,
        skills: MailSkills,
        draft_store: DraftStore,
        subjects: ConfirmationSubjectResolver | None = None,
    ) -> None:
        self._skills = skills
        self._draft_store = draft_store
        self._subjects = subjects or ConfirmationSubjectResolver(skills.read, skills.management)

    async def present(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        user: UserContext,
    ) -> ConfirmationRequest:
        """Build the confirmation request shown for a suspended tool call.

        The request returned here is the one that will authorise the operation
        and appear in the audit trail, so what the user reads is exactly what
        gets enforced and recorded.

        Raises:
            UnknownGatedToolError: the capability cannot be described. Failing
                here is deliberate: approving an operation nobody can explain
                would be worse than interrupting the conversation.
        """
        tool = self._tool_for(tool_name)
        if tool is MailToolName.SEND_MAIL:
            return self._present_send(arguments, user)
        if tool in _HOUSEKEEPING:
            return await self._present_housekeeping(tool, arguments, user)
        if tool in _LABEL_LIFECYCLE:
            return await self._present_label_lifecycle(tool, arguments, user)
        raise UnknownGatedToolError(tool_name)

    def _present_send(self, arguments: Mapping[str, Any], user: UserContext) -> ConfirmationRequest:
        """Resolve the draft so the user sees what would actually be delivered."""
        reference = str(arguments.get("draft_reference", ""))
        draft = self._draft_store.get(reference, user)
        return self._skills.send.build_confirmation_request(draft, user, target=reference)

    async def _present_housekeeping(
        self,
        tool: MailToolName,
        arguments: Mapping[str, Any],
        user: UserContext,
    ) -> ConfirmationRequest:
        """Describe a mailbox change in the user's terms."""
        message_id = str(arguments.get("message_id", ""))
        label_id = self._optional_str(arguments.get("label_id"))
        is_read = arguments.get("is_read")
        described = await self._subjects.message(message_id, user)
        return self._skills.management.build_confirmation_request(
            tool,
            message_id,
            user,
            label_id=label_id,
            label_name=None if label_id is None else await self._subjects.label_name(label_id, user),
            is_read=is_read if isinstance(is_read, bool) else None,
            subject=None if described is None else described.subject,
            sender=None if described is None else described.sender,
            target=housekeeping_target(message_id, label_id),
        )

    async def _present_label_lifecycle(
        self,
        tool: MailToolName,
        arguments: Mapping[str, Any],
        user: UserContext,
    ) -> ConfirmationRequest:
        """Describe a change to the label set of the mailbox.

        Creation names a label that does not exist yet, so the argument is
        already the readable one; deletion names an identifier, which is not.
        """
        if tool is MailToolName.CREATE_LABEL:
            return self._skills.management.build_label_confirmation_request(
                tool, str(arguments.get("name", "")), user
            )
        label_id = str(arguments.get("label_id", ""))
        return self._skills.management.build_label_confirmation_request(
            tool,
            label_id,
            user,
            label_name=await self._subjects.label_name(label_id, user),
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
