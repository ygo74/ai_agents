"""Mailbox housekeeping: read state, archiving and labels."""

from __future__ import annotations

from ai_agent_lab.domain.mail.models import MailLabel
from ai_agent_lab.domain.mail.permissions import MailPermission
from ai_agent_lab.domain.security.confirmation import (
    ConfirmationDecision,
    ConfirmationDetail,
    ConfirmationRequest,
)
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.mcp.mail.catalog import MailToolName
from ai_agent_lab.mcp.mail.contracts import MailOrganisationTools, MailReadTools
from ai_agent_lab.skills.mail.gating import GatedMailOperationRunner


class MailManagementSkill:
    """Changes the state of messages in the mailbox.

    Every operation here modifies the mailbox, so every one of them goes through
    the confirmation policy. The skill has no way to reach the MCP tools other
    than through the gated runner.
    """

    def __init__(
        self,
        read_tools: MailReadTools,
        organisation_tools: MailOrganisationTools,
        runner: GatedMailOperationRunner,
    ) -> None:
        self._read_tools = read_tools
        self._organisation_tools = organisation_tools
        self._runner = runner

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        user.require_permission(MailPermission.READ)
        return await self._read_tools.list_labels(user)

    def requires_confirmation(self, tool: MailToolName, user: UserContext) -> bool:
        """Whether a housekeeping operation currently needs an approval."""
        return self._runner.requires_confirmation(tool, user)

    def build_confirmation_request(
        self,
        tool: MailToolName,
        message_id: str,
        user: UserContext,
        *,
        label_id: str | None = None,
        is_read: bool | None = None,
        target: str = "",
    ) -> ConfirmationRequest:
        """Describe a housekeeping operation so the user can approve it."""
        details = [ConfirmationDetail(label="Message", value=message_id)]
        if label_id is not None:
            details.append(ConfirmationDetail(label="Label", value=label_id))
        if is_read is not None:
            details.append(ConfirmationDetail(label="New state", value="read" if is_read else "unread"))
        return self._runner.build_confirmation_request(
            tool,
            user,
            _TITLES[tool],
            target=target or message_id,
            details=details,
        )

    async def set_read_state(
        self,
        message_id: str,
        is_read: bool,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> None:
        """Mark a message as read or unread."""
        await self._runner.execute(
            MailToolName.MARK_READ,
            user,
            lambda: self._organisation_tools.set_read_state(message_id, is_read, user),
            target_id=message_id,
            request=request,
            decision=decision,
        )

    async def archive(
        self,
        message_id: str,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> None:
        """Remove a message from the inbox without deleting it."""
        await self._runner.execute(
            MailToolName.ARCHIVE_MAIL,
            user,
            lambda: self._organisation_tools.archive(message_id, user),
            target_id=message_id,
            request=request,
            decision=decision,
        )

    async def apply_label(
        self,
        message_id: str,
        label_id: str,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> None:
        """Attach a label or category to a message."""
        await self._runner.execute(
            MailToolName.APPLY_LABEL,
            user,
            lambda: self._organisation_tools.apply_label(message_id, label_id, user),
            target_id=message_id,
            request=request,
            decision=decision,
        )

    async def remove_label(
        self,
        message_id: str,
        label_id: str,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> None:
        """Detach a label or category from a message."""
        await self._runner.execute(
            MailToolName.REMOVE_LABEL,
            user,
            lambda: self._organisation_tools.remove_label(message_id, label_id, user),
            target_id=message_id,
            request=request,
            decision=decision,
        )


_TITLES: dict[MailToolName, str] = {
    MailToolName.MARK_READ: "Change the read state of this message?",
    MailToolName.ARCHIVE_MAIL: "Archive this message?",
    MailToolName.APPLY_LABEL: "Apply this label to the message?",
    MailToolName.REMOVE_LABEL: "Remove this label from the message?",
}
