"""Mapping between the mail protocol and the mail domain.

The protocol carries plain text; the domain carries typed models in which
third-party text is fenced as :class:`UntrustedText`. Fencing happens here, once,
on the way in, so no caller can forget it.

This is the agent side of the boundary. A server never imports it.
"""

from __future__ import annotations

import logging

from ygo74.agent_runtime.domains.security.untrusted import untrusted

from ai_agent_lab.mail.domain.enums import MailImportance
from ai_agent_lab.mail.domain.models import (
    EmailAddress,
    MailAttachment,
    MailDraft,
    MailHeader,
    MailLabel,
    MailLabelOutcome,
    MailMessage,
    MailParticipant,
    MailSearchResult,
    MailSendResult,
    MailThread,
)
from ai_agent_lab.mail.domain.origins import MailOrigin
from mail_mcp.protocol import payloads as wire

_logger = logging.getLogger(__name__)


class MailWireMapper:
    """Turns protocol payloads into domain models, and drafts back out."""

    def participant(self, payload: wire.Participant) -> MailParticipant:
        """Rebuild a participant, fencing the display name."""
        _logger.debug(
            "MailWireMapper.participant arguments: address_present=%s, display_name_present=%s",
            bool(payload.address),
            payload.display_name is not None,
        )
        return MailParticipant(
            address=EmailAddress(value=payload.address),
            display_name=(
                None
                if payload.display_name is None
                else untrusted(payload.display_name, MailOrigin.SENDER_NAME)
            ),
        )

    def attachment(self, payload: wire.Attachment) -> MailAttachment:
        """Rebuild attachment metadata, fencing the file name."""
        _logger.debug(
            "MailWireMapper.attachment arguments: attachment_id=%s, file_name_length=%d, media_type=%s, size_bytes=%d",
            payload.attachment_id,
            len(payload.file_name),
            payload.media_type,
            payload.size_bytes,
        )
        return MailAttachment(
            attachment_id=payload.attachment_id,
            file_name=untrusted(payload.file_name, MailOrigin.ATTACHMENT_NAME),
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
        )

    def label(self, payload: wire.Label) -> MailLabel:
        """Rebuild a label, fencing its name."""
        _logger.debug(
            "MailWireMapper.label arguments: label_id=%s, name_length=%d, is_system=%s",
            payload.label_id,
            len(payload.name),
            payload.is_system,
        )
        return MailLabel(
            label_id=payload.label_id,
            name=untrusted(payload.name, MailOrigin.LABEL),
            is_system=payload.is_system,
        )

    def labels(self, payload: wire.Labels) -> tuple[MailLabel, ...]:
        """Rebuild every label of a mailbox."""
        _logger.info("Mapping native Mail MCP label loop")
        _logger.debug("MailWireMapper.labels arguments: labels=%d", len(payload.labels))
        return tuple(self.label(item) for item in payload.labels)

    def label_outcome(self, payload: wire.CreatedLabel) -> MailLabelOutcome:
        """Rebuild the outcome of asking for a label to exist."""
        _logger.info("Mapping native Mail MCP label outcome")
        _logger.debug(
            "MailWireMapper.label_outcome arguments: label_id=%s, created=%s",
            payload.label.label_id,
            payload.created,
        )
        return MailLabelOutcome(label=self.label(payload.label), created=payload.created)

    def header(self, payload: wire.Header) -> MailHeader:
        """Rebuild a search hit, fencing the subject."""
        _logger.debug(
            "MailWireMapper.header arguments: message_id=%s, thread_id=%s, subject_length=%d, recipient_count=%d",
            payload.message_id,
            payload.thread_id,
            len(payload.subject),
            payload.recipient_count,
        )
        return MailHeader(
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            subject=untrusted(payload.subject, MailOrigin.SUBJECT),
            sender=self.participant(payload.sender),
            recipient_count=payload.recipient_count,
            sent_at=payload.sent_at,
            is_read=payload.is_read,
            is_archived=payload.is_archived,
            has_attachments=payload.has_attachments,
            importance=MailImportance(payload.importance.value),
            label_ids=payload.label_ids,
        )

    def message(self, payload: wire.Message) -> MailMessage:
        """Rebuild a complete message, fencing subject and body."""
        _logger.debug(
            "MailWireMapper.message arguments: message_id=%s, thread_id=%s, "
            "subject_length=%d, body_length=%d, to_count=%d, cc_count=%d, "
            "attachments=%d",
            payload.message_id,
            payload.thread_id,
            len(payload.subject),
            len(payload.body),
            len(payload.to),
            len(payload.cc),
            len(payload.attachments),
        )
        return MailMessage(
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            subject=untrusted(payload.subject, MailOrigin.SUBJECT),
            body=untrusted(payload.body, MailOrigin.BODY),
            sender=self.participant(payload.sender),
            to=tuple(self.participant(item) for item in payload.to),
            cc=tuple(self.participant(item) for item in payload.cc),
            sent_at=payload.sent_at,
            is_read=payload.is_read,
            is_archived=payload.is_archived,
            importance=MailImportance(payload.importance.value),
            label_ids=payload.label_ids,
            attachments=tuple(self.attachment(item) for item in payload.attachments),
            in_reply_to=payload.in_reply_to,
        )

    def thread(self, payload: wire.Thread) -> MailThread:
        """Rebuild a conversation."""
        _logger.info("Mapping native Mail MCP thread message loop")
        _logger.debug(
            "MailWireMapper.thread arguments: thread_id=%s, subject_length=%d, messages=%d",
            payload.thread_id,
            len(payload.subject),
            len(payload.messages),
        )
        return MailThread(
            thread_id=payload.thread_id,
            subject=untrusted(payload.subject, MailOrigin.SUBJECT),
            messages=tuple(self.message(item) for item in payload.messages),
        )

    def search_result(self, payload: wire.SearchResult) -> MailSearchResult:
        """Rebuild the outcome of a query."""
        _logger.info("Mapping native Mail MCP search result loop")
        _logger.debug(
            "MailWireMapper.search_result arguments: headers=%d, total_count=%d, truncated=%s",
            len(payload.headers),
            payload.total_count,
            payload.truncated,
        )
        return MailSearchResult(
            headers=tuple(self.header(item) for item in payload.headers),
            total_count=payload.total_count,
            truncated=payload.truncated,
        )

    def send_result(self, payload: wire.SendResult) -> MailSendResult:
        """Rebuild the outcome of a delivery."""
        _logger.info("Mapping native Mail MCP send result")
        _logger.debug(
            "MailWireMapper.send_result arguments: message_id=%s, thread_id=%s, sent_at=%s",
            payload.message_id,
            payload.thread_id,
            payload.sent_at.isoformat(),
        )
        return MailSendResult(
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            sent_at=payload.sent_at,
        )

    def draft(self, payload: wire.Draft) -> MailDraft:
        """Rebuild a draft, fencing subject and body."""
        _logger.info("Mapping native Mail MCP draft recipient loops")
        _logger.debug(
            "MailWireMapper.draft arguments: draft_id=%s, to_count=%d, cc_count=%d, subject_length=%d, body_length=%d",
            payload.draft_id,
            len(payload.to),
            len(payload.cc),
            len(payload.subject),
            len(payload.body),
        )
        return MailDraft(
            draft_id=payload.draft_id,
            to=tuple(EmailAddress(value=item) for item in payload.to),
            cc=tuple(EmailAddress(value=item) for item in payload.cc),
            subject=untrusted(payload.subject, MailOrigin.SUBJECT),
            body=untrusted(payload.body, MailOrigin.BODY),
            in_reply_to_message_id=payload.in_reply_to_message_id,
            thread_id=payload.thread_id,
        )

    def to_wire(self, draft: MailDraft) -> wire.Draft:
        """Project a draft onto the wire, so a server can store or send it."""
        _logger.info("Mapping Mail draft to native MCP recipient loops")
        _logger.debug(
            "MailWireMapper.to_wire arguments: draft_id=%s, to_count=%d, cc_count=%d, "
            "subject_length=%d, body_length=%d",
            draft.draft_id,
            len(draft.to),
            len(draft.cc),
            len(draft.subject.expose()),
            len(draft.body.expose()),
        )
        return wire.Draft(
            draft_id=draft.draft_id,
            to=tuple(address.value for address in draft.to),
            cc=tuple(address.value for address in draft.cc),
            subject=draft.subject.expose(),
            body=draft.body.expose(),
            in_reply_to_message_id=draft.in_reply_to_message_id,
            thread_id=draft.thread_id,
        )
