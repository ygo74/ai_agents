"""Delivery of a prepared message, behind an explicit user confirmation."""

from __future__ import annotations

import logging

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationDetail,
    ConfirmationRequest,
)
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.domain.models import MailDraft, MailSendRequest, MailSendResult
from ai_agent_lab.mail.skills.gating import GatedMailOperationRunner
from ai_agent_lab.mail.tools_port import MailDraftTools, MailSendTools

_BODY_PREVIEW_CHARACTERS = 600
_logger = logging.getLogger(__name__)


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
        _logger.info("Initializing Mail send skill")
        _logger.debug(
            "SendMailSkill.__init__ arguments: draft_tools_type=%s, send_tools_type=%s, runner_type=%s",
            type(draft_tools).__name__,
            type(send_tools).__name__,
            type(runner).__name__,
        )
        self._draft_tools = draft_tools
        self._send_tools = send_tools
        self._runner = runner

    def requires_confirmation(self, user: UserContext) -> bool:
        """Whether delivering a message currently needs an approval."""
        _logger.info("Checking Mail send confirmation requirement")
        _logger.debug("SendMailSkill.requires_confirmation arguments: user_id=%s", user.user_id)
        return self._runner.requires_confirmation(MailToolName.SEND_MAIL, user)

    def build_confirmation_request(
        self,
        draft: MailDraft,
        user: UserContext,
        *,
        target: str = "",
    ) -> ConfirmationRequest:
        """Describe the delivery so the user can decide with full knowledge.

        The details reach a human, never a log or a trace.
        """
        _logger.info("Building Mail send confirmation request")
        _logger.debug(
            "SendMailSkill.build_confirmation_request arguments: user_id=%s, "
            "to_count=%d, cc_count=%d, subject_length=%d, body_length=%d, "
            "target=%s",
            user.user_id,
            len(draft.to),
            len(draft.cc),
            len(draft.subject.expose()),
            len(draft.body.expose()),
            target,
        )
        details = [
            ConfirmationDetail(label="To", value=", ".join(str(address) for address in draft.to)),
            ConfirmationDetail(label="Subject", value=draft.subject.expose()),
            ConfirmationDetail(label="Body", value=self._preview(draft.body.expose())),
        ]
        if draft.cc:
            details.insert(1, ConfirmationDetail(label="Cc", value=", ".join(str(a) for a in draft.cc)))
        return self._runner.build_confirmation_request(
            MailToolName.SEND_MAIL,
            user,
            "Send this email?",
            target=target,
            details=details,
        )

    async def save_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Store the draft in the mailbox without delivering it."""
        _logger.info("Saving Mail draft")
        _logger.debug(
            "SendMailSkill.save_draft arguments: user_id=%s, to_count=%d, cc_count=%d, "
            "subject_length=%d, body_length=%d, in_reply_to=%s",
            user.user_id,
            len(draft.to),
            len(draft.cc),
            len(draft.subject.expose()),
            len(draft.body.expose()),
            draft.in_reply_to_message_id,
        )
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
            PermissionDeniedError: the user may not send mail.
        """
        _logger.info("Sending approved Mail draft")
        _logger.debug(
            "SendMailSkill.send arguments: user_id=%s, to_count=%d, cc_count=%d, "
            "subject_length=%d, body_length=%d, in_reply_to=%s, "
            "request_id=%s, decision_present=%s",
            user.user_id,
            len(draft.to),
            len(draft.cc),
            len(draft.subject.expose()),
            len(draft.body.expose()),
            draft.in_reply_to_message_id,
            None if request is None else request.request_id,
            decision is not None,
        )
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
        _logger.info("Building Mail body confirmation preview")
        _logger.debug(
            "SendMailSkill._preview arguments: body_length=%d, limit=%d",
            len(body),
            _BODY_PREVIEW_CHARACTERS,
        )
        if len(body) <= _BODY_PREVIEW_CHARACTERS:
            return body
        return body[:_BODY_PREVIEW_CHARACTERS] + "\n[...]"
