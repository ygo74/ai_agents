"""Mailbox housekeeping: read state, archiving and labels."""

from __future__ import annotations

import logging

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationDetail,
    ConfirmationRequest,
)
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.domain.models import MailLabel, MailLabelOutcome
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.skills.gating import GatedMailOperationRunner
from ai_agent_lab.mail.tools_port import MailLabelTools, MailOrganisationTools, MailReadTools

_logger = logging.getLogger(__name__)


class MailManagementSkill:
    """Changes the state of messages in the mailbox, and its label set.

    Every operation here modifies the mailbox, so every one of them goes through
    the confirmation policy. The skill has no way to reach the MCP tools other
    than through the gated runner.
    """

    def __init__(
        self,
        read_tools: MailReadTools,
        organisation_tools: MailOrganisationTools,
        label_tools: MailLabelTools,
        runner: GatedMailOperationRunner,
    ) -> None:
        _logger.info("Initializing Mail management skill")
        _logger.debug(
            "MailManagementSkill.__init__ arguments: read_tools_type=%s, "
            "organisation_tools_type=%s, label_tools_type=%s, runner_type=%s",
            type(read_tools).__name__,
            type(organisation_tools).__name__,
            type(label_tools).__name__,
            type(runner).__name__,
        )
        self._read_tools = read_tools
        self._organisation_tools = organisation_tools
        self._label_tools = label_tools
        self._runner = runner

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        _logger.info("Listing mailbox labels")
        _logger.debug("MailManagementSkill.list_labels arguments: user_id=%s", user.user_id)
        user.require_permission(MailPermission.READ)
        return await self._read_tools.list_labels(user)

    def requires_confirmation(self, tool: MailToolName, user: UserContext) -> bool:
        """Whether a housekeeping operation currently needs an approval."""
        _logger.info("Checking Mail management confirmation requirement")
        _logger.debug(
            "MailManagementSkill.requires_confirmation arguments: tool_name=%s, user_id=%s",
            tool.value,
            user.user_id,
        )
        return self._runner.requires_confirmation(tool, user)

    def build_confirmation_request(
        self,
        tool: MailToolName,
        message_id: str,
        user: UserContext,
        *,
        label_id: str | None = None,
        label_name: str | None = None,
        is_read: bool | None = None,
        subject: str | None = None,
        sender: str | None = None,
        target: str = "",
    ) -> ConfirmationRequest:
        """Describe a housekeeping operation so the user can approve it.

        The identifiers stay in the request because they are what gets enforced
        and audited. The readable facts are added next to them, when a caller
        could resolve them, so the person deciding recognises the message.
        """
        _logger.info("Building Mail management confirmation request")
        _logger.debug(
            "MailManagementSkill.build_confirmation_request arguments: tool_name=%s, "
            "message_id=%s, user_id=%s, label_id=%s, label_name_present=%s, "
            "is_read=%s, subject_length=%s, sender_present=%s, target=%s",
            tool.value,
            message_id,
            user.user_id,
            label_id,
            label_name is not None,
            is_read,
            None if subject is None else len(subject),
            sender is not None,
            target,
        )
        details = [ConfirmationDetail(label="Message", value=message_id)]
        if subject is not None:
            details.append(ConfirmationDetail(label="Subject", value=subject))
        if sender is not None:
            details.append(ConfirmationDetail(label="From", value=sender))
        if label_id is not None:
            details.append(ConfirmationDetail(label="Label", value=_named(label_id, label_name)))
        if is_read is not None:
            details.append(ConfirmationDetail(label="New state", value="read" if is_read else "unread"))
        return self._runner.build_confirmation_request(
            tool,
            user,
            _TITLES[tool],
            target=target or message_id,
            details=details,
        )

    def build_label_confirmation_request(
        self,
        tool: MailToolName,
        label: str,
        user: UserContext,
        *,
        label_name: str | None = None,
    ) -> ConfirmationRequest:
        """Describe a change to the label set so the user can approve it.

        A separate builder because these operations name no message. Reusing
        the message one would have meant inventing an identifier, and the
        target is what the answer is matched against.
        """
        _logger.info("Building Mail label confirmation request")
        _logger.debug(
            "MailManagementSkill.build_label_confirmation_request arguments: "
            "tool_name=%s, label_length=%d, user_id=%s, label_name_present=%s",
            tool.value,
            len(label),
            user.user_id,
            label_name is not None,
        )
        return self._runner.build_confirmation_request(
            tool,
            user,
            _TITLES[tool],
            target=label,
            details=[ConfirmationDetail(label="Label", value=_named(label, label_name))],
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
        _logger.info("Changing mailbox message read state")
        _logger.debug(
            "MailManagementSkill.set_read_state arguments: message_id=%s, is_read=%s, "
            "user_id=%s, request_id=%s, decision_present=%s",
            message_id,
            is_read,
            user.user_id,
            None if request is None else request.request_id,
            decision is not None,
        )
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
        _logger.info("Archiving mailbox message")
        _logger.debug(
            "MailManagementSkill.archive arguments: message_id=%s, user_id=%s, request_id=%s, decision_present=%s",
            message_id,
            user.user_id,
            None if request is None else request.request_id,
            decision is not None,
        )
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
        _logger.info("Applying mailbox label")
        _logger.debug(
            "MailManagementSkill.apply_label arguments: message_id=%s, label_id=%s, "
            "user_id=%s, request_id=%s, decision_present=%s",
            message_id,
            label_id,
            user.user_id,
            None if request is None else request.request_id,
            decision is not None,
        )
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
        _logger.info("Removing mailbox label")
        _logger.debug(
            "MailManagementSkill.remove_label arguments: message_id=%s, label_id=%s, "
            "user_id=%s, request_id=%s, decision_present=%s",
            message_id,
            label_id,
            user.user_id,
            None if request is None else request.request_id,
            decision is not None,
        )
        await self._runner.execute(
            MailToolName.REMOVE_LABEL,
            user,
            lambda: self._organisation_tools.remove_label(message_id, label_id, user),
            target_id=message_id,
            request=request,
            decision=decision,
        )

    async def create_label(
        self,
        name: str,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> MailLabelOutcome:
        """Make a label exist, reporting whether it had to be created."""
        _logger.info("Creating mailbox label")
        _logger.debug(
            "MailManagementSkill.create_label arguments: name_length=%d, user_id=%s, "
            "request_id=%s, decision_present=%s",
            len(name),
            user.user_id,
            None if request is None else request.request_id,
            decision is not None,
        )
        return await self._runner.execute(
            MailToolName.CREATE_LABEL,
            user,
            lambda: self._label_tools.create_label(name, user),
            target_id=name,
            request=request,
            decision=decision,
        )

    async def delete_label(
        self,
        label_id: str,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> None:
        """Delete a label, detaching it from every message carrying it."""
        _logger.info("Deleting mailbox label")
        _logger.debug(
            "MailManagementSkill.delete_label arguments: label_id=%s, user_id=%s, request_id=%s, decision_present=%s",
            label_id,
            user.user_id,
            None if request is None else request.request_id,
            decision is not None,
        )
        await self._runner.execute(
            MailToolName.DELETE_LABEL,
            user,
            lambda: self._label_tools.delete_label(label_id, user),
            target_id=label_id,
            request=request,
            decision=decision,
        )


_TITLES: dict[MailToolName, str] = {
    MailToolName.MARK_READ: "Change the read state of this message?",
    MailToolName.ARCHIVE_MAIL: "Archive this message?",
    MailToolName.APPLY_LABEL: "Apply this label to the message?",
    MailToolName.REMOVE_LABEL: "Remove this label from the message?",
    MailToolName.CREATE_LABEL: "Create this label in the mailbox?",
    MailToolName.DELETE_LABEL: "Delete this label from the mailbox, and from every message carrying it?",
}


def _named(identifier: str, name: str | None) -> str:
    """Render an identifier with the name a person would recognise it by."""
    return identifier if not name else f"{name} ({identifier})"
