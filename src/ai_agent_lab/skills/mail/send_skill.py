"""Delivery of a prepared message, behind an explicit user confirmation."""

from __future__ import annotations

from ai_agent_lab.domain.mail.models import MailDraft, MailSendRequest, MailSendResult
from ai_agent_lab.domain.security.confirmation import (
    ConfirmationDecision,
    ConfirmationDetail,
    ConfirmationRequest,
)
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.mcp.mail.catalog import MailToolName
from ai_agent_lab.mcp.mail.contracts import MailDraftTools, MailSendTools
from ai_agent_lab.skills.mail.gating import GatedMailOperationRunner

_BODY_PREVIEW_CHARACTERS = 600


class SendMailSkill:
    """Saves drafts and delivers them once the user has approved.

    Sending is irreversible, so the skill re-checks the confirmation policy
    itself. The framework adapter already suspends the call, but this second
    check means the guarantee survives being driven by another framework, a
    script or a test.
    """

    def __init__(
        self,
        draft_tools: MailDraftTools,
        send_tools: MailSendTools,
        runner: GatedMailOperationRunner,
    ) -> None:
        self._draft_tools = draft_tools
        self._send_tools = send_tools
        self._runner = runner

    def requires_confirmation(self, user: UserContext) -> bool:
        """Whether delivering a message currently needs an approval."""
        return self._runner.requires_confirmation(MailToolName.SEND_MAIL, user)

    def build_confirmation_request(self, draft: MailDraft) -> ConfirmationRequest:
        """Describe the delivery so the user can decide with full knowledge.

        The details reach a human, never a log or a trace.
        """
        details = [
            ConfirmationDetail(label="To", value=", ".join(str(address) for address in draft.to)),
            ConfirmationDetail(label="Subject", value=draft.subject.expose()),
            ConfirmationDetail(label="Body", value=self._preview(draft.body.expose())),
        ]
        if draft.cc:
            details.insert(1, ConfirmationDetail(label="Cc", value=", ".join(str(a) for a in draft.cc)))
        return self._runner.build_confirmation_request(
            MailToolName.SEND_MAIL,
            title="Send this email?",
            details=details,
        )

    async def save_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Store the draft in the mailbox without delivering it."""
        return await self._runner.execute(
            MailToolName.CREATE_DRAFT,
            user,
            lambda: self._draft_tools.create_draft(draft, user),
            target_id=draft.in_reply_to_message_id,
        )

    async def send(
        self,
        draft: MailDraft,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> MailSendResult:
        """Deliver the draft, once and only after an explicit approval.

        Raises:
            ConfirmationRequiredError: the user has not been asked yet.
            ConfirmationRejectedError: the user declined the delivery.
            AuthorizationError: the user may not send mail.
        """
        return await self._runner.execute(
            MailToolName.SEND_MAIL,
            user,
            lambda: self._send_tools.send(MailSendRequest(draft=draft), user),
            target_id=draft.in_reply_to_message_id,
            request=request,
            decision=decision,
        )

    @staticmethod
    def _preview(body: str) -> str:
        """Shorten a body so the confirmation stays readable."""
        if len(body) <= _BODY_PREVIEW_CHARACTERS:
            return body
        return body[:_BODY_PREVIEW_CHARACTERS] + "\n[...]"
