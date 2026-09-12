"""Drafting of a reply. This skill never sends anything."""

from __future__ import annotations

import logging

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.mail.domain.errors import NoReplyRecipientError
from ai_agent_lab.mail.domain.models import (
    EmailAddress,
    MailDraft,
    MailMessage,
    MailParticipant,
)
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.domain.ports import MailboxOwnerDirectory
from ai_agent_lab.mail.skills.analysis import MailReplyOutput
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.tools_port import MailReadTools

_REPLY_PREFIX = "Re: "
_logger = logging.getLogger(__name__)


class ReplyRecipientPlanner:
    """Decides who a reply goes to.

    This is a deterministic rule, so it is implemented in code rather than
    delegated to a model: a mistake here means a message reaching the wrong
    people.
    """

    def plan(
        self,
        message: MailMessage,
        owner: EmailAddress,
        *,
        reply_all: bool,
    ) -> tuple[tuple[EmailAddress, ...], tuple[EmailAddress, ...]]:
        """Return the ``to`` and ``cc`` lists of a reply."""
        _logger.info("Planning Mail reply recipients")
        _logger.debug(
            "ReplyRecipientPlanner.plan arguments: message_id=%s, to_count=%d, cc_count=%d, reply_all=%s",
            message.message_id,
            len(message.to),
            len(message.cc),
            reply_all,
        )
        primary = self._unique((message.sender,), exclude={owner})
        if not reply_all:
            return self._require_recipients(primary, message), ()

        others = self._unique((*message.to, *message.cc), exclude={owner, *primary})
        if primary:
            return primary, others
        return self._require_recipients(others, message), ()

    @staticmethod
    def _unique(
        participants: tuple[MailParticipant, ...],
        *,
        exclude: set[EmailAddress],
    ) -> tuple[EmailAddress, ...]:
        """Collect distinct addresses, dropping the excluded ones."""
        _logger.info("Collecting unique Mail reply recipient loop")
        _logger.debug(
            "ReplyRecipientPlanner._unique arguments: participants=%d, excluded=%d",
            len(participants),
            len(exclude),
        )
        seen: dict[str, EmailAddress] = {}
        for participant in participants:
            address = participant.address
            if address in exclude:
                continue
            seen.setdefault(address.value, address)
        return tuple(seen.values())

    @staticmethod
    def _require_recipients(
        recipients: tuple[EmailAddress, ...],
        message: MailMessage,
    ) -> tuple[EmailAddress, ...]:
        """Fail rather than produce a reply nobody would receive."""
        _logger.info("Validating Mail reply recipients")
        _logger.debug(
            "ReplyRecipientPlanner._require_recipients arguments: recipients=%d, message_id=%s",
            len(recipients),
            message.message_id,
        )
        if not recipients:
            raise NoReplyRecipientError(message.message_id)
        return recipients


class MailReplySkill:
    """Prepares a reply to a message or a conversation.

    The result is a draft. Delivering it is a separate, explicitly gated
    capability, so drafting can never turn into sending by accident.
    """

    def __init__(
        self,
        mail_tools: MailReadTools,
        reasoner: TextReasoner,
        context_builder: MailContextBuilder,
        owner_directory: MailboxOwnerDirectory,
        recipient_planner: ReplyRecipientPlanner,
        instructions: str,
    ) -> None:
        _logger.info("Initializing Mail reply skill")
        _logger.debug(
            "MailReplySkill.__init__ arguments: mail_tools_type=%s, reasoner_type=%s, "
            "context_builder_type=%s, owner_directory_type=%s, "
            "recipient_planner_type=%s, instructions_length=%d",
            type(mail_tools).__name__,
            type(reasoner).__name__,
            type(context_builder).__name__,
            type(owner_directory).__name__,
            type(recipient_planner).__name__,
            len(instructions),
        )
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._owner_directory = owner_directory
        self._recipient_planner = recipient_planner
        self._instructions = instructions

    async def draft_reply_to_message(
        self,
        message_id: str,
        intent: str,
        user: UserContext,
        *,
        reply_all: bool = False,
    ) -> MailDraft:
        """Draft a reply to a single message."""
        _logger.info("Drafting Mail reply to message")
        _logger.debug(
            "MailReplySkill.draft_reply_to_message arguments: message_id=%s, "
            "intent_length=%d, user_id=%s, reply_all=%s",
            message_id,
            len(intent),
            user.user_id,
            reply_all,
        )
        user.require_permission(MailPermission.DRAFT)
        message = await self._mail_tools.get_message(message_id, user)
        return await self._draft(message, (message,), intent, user, reply_all=reply_all)

    async def draft_reply_to_thread(
        self,
        thread_id: str,
        intent: str,
        user: UserContext,
        *,
        reply_all: bool = False,
    ) -> MailDraft:
        """Draft a reply to the most recent message of a conversation."""
        _logger.info("Drafting Mail reply to thread")
        _logger.debug(
            "MailReplySkill.draft_reply_to_thread arguments: thread_id=%s, intent_length=%d, user_id=%s, reply_all=%s",
            thread_id,
            len(intent),
            user.user_id,
            reply_all,
        )
        user.require_permission(MailPermission.DRAFT)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._draft(
            thread.latest_message,
            thread.in_chronological_order(),
            intent,
            user,
            reply_all=reply_all,
        )

    async def _draft(
        self,
        replied_to: MailMessage,
        context: tuple[MailMessage, ...],
        intent: str,
        user: UserContext,
        *,
        reply_all: bool,
    ) -> MailDraft:
        """Compose the draft: deterministic recipients, generated wording."""
        _logger.info("Composing Mail reply draft")
        _logger.debug(
            "MailReplySkill._draft arguments: message_id=%s, context_count=%d, "
            "intent_length=%d, user_id=%s, reply_all=%s",
            replied_to.message_id,
            len(context),
            len(intent),
            user.user_id,
            reply_all,
        )
        owner = self._owner_directory.address_of(user)
        to, cc = self._recipient_planner.plan(replied_to, owner, reply_all=reply_all)

        request = ReasoningRequest(
            instructions=self._instructions,
            task=f"Draft a reply to message {replied_to.message_id}. Intent stated by the owner: {intent}",
            context=self._context_builder.build(context),
        )
        output = await self._reasoner.reason(request, MailReplyOutput)

        return MailDraft(
            to=to,
            cc=cc,
            subject=untrusted(self._subject_for(output, replied_to), UntrustedOrigin.MAIL_SUBJECT),
            body=untrusted(output.body.strip(), UntrustedOrigin.MAIL_BODY),
            in_reply_to_message_id=replied_to.message_id,
            thread_id=replied_to.thread_id,
        )

    @staticmethod
    def _subject_for(output: MailReplyOutput, replied_to: MailMessage) -> str:
        """Use the generated subject, or derive one from the original message."""
        _logger.info("Selecting Mail reply subject")
        _logger.debug(
            "MailReplySkill._subject_for arguments: generated_subject_length=%d, "
            "message_id=%s, original_subject_length=%d",
            len(output.subject),
            replied_to.message_id,
            len(replied_to.subject.expose()),
        )
        proposed = output.subject.strip()
        if proposed:
            return proposed
        original = replied_to.subject.expose().strip()
        if original.casefold().startswith(_REPLY_PREFIX.casefold()):
            return original
        return f"{_REPLY_PREFIX}{original}"
