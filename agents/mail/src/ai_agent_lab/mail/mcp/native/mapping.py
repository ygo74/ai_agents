"""Mapping between the mail protocol and the mail domain.

The protocol carries plain text; the domain carries typed models in which
third-party text is fenced as :class:`UntrustedText`. Fencing happens here, once,
on the way in, so no caller can forget it.

This is the agent side of the boundary. A server never imports it.
"""

from __future__ import annotations

from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.mail.domain.enums import MailImportance
from ai_agent_lab.mail.domain.models import (
    EmailAddress,
    MailAttachment,
    MailDraft,
    MailHeader,
    MailLabel,
    MailMessage,
    MailParticipant,
    MailSearchResult,
    MailSendResult,
    MailThread,
)
from mail_mcp.protocol import payloads as wire


class MailWireMapper:
    """Turns protocol payloads into domain models, and drafts back out."""

    def participant(self, payload: wire.Participant) -> MailParticipant:
        """Rebuild a participant, fencing the display name."""
        return MailParticipant(
            address=EmailAddress(value=payload.address),
            display_name=(
                None
                if payload.display_name is None
                else untrusted(payload.display_name, UntrustedOrigin.MAIL_SENDER_NAME)
            ),
        )

    def attachment(self, payload: wire.Attachment) -> MailAttachment:
        """Rebuild attachment metadata, fencing the file name."""
        return MailAttachment(
            attachment_id=payload.attachment_id,
            file_name=untrusted(payload.file_name, UntrustedOrigin.MAIL_ATTACHMENT_NAME),
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
        )

    def label(self, payload: wire.Label) -> MailLabel:
        """Rebuild a label, fencing its name."""
        return MailLabel(
            label_id=payload.label_id,
            name=untrusted(payload.name, UntrustedOrigin.MAIL_LABEL),
            is_system=payload.is_system,
        )

    def labels(self, payload: wire.Labels) -> tuple[MailLabel, ...]:
        """Rebuild every label of a mailbox."""
        return tuple(self.label(item) for item in payload.labels)

    def header(self, payload: wire.Header) -> MailHeader:
        """Rebuild a search hit, fencing the subject."""
        return MailHeader(
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            subject=untrusted(payload.subject, UntrustedOrigin.MAIL_SUBJECT),
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
        return MailMessage(
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            subject=untrusted(payload.subject, UntrustedOrigin.MAIL_SUBJECT),
            body=untrusted(payload.body, UntrustedOrigin.MAIL_BODY),
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
        return MailThread(
            thread_id=payload.thread_id,
            subject=untrusted(payload.subject, UntrustedOrigin.MAIL_SUBJECT),
            messages=tuple(self.message(item) for item in payload.messages),
        )

    def search_result(self, payload: wire.SearchResult) -> MailSearchResult:
        """Rebuild the outcome of a query."""
        return MailSearchResult(
            headers=tuple(self.header(item) for item in payload.headers),
            total_count=payload.total_count,
            truncated=payload.truncated,
        )

    def send_result(self, payload: wire.SendResult) -> MailSendResult:
        """Rebuild the outcome of a delivery."""
        return MailSendResult(
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            sent_at=payload.sent_at,
        )

    def draft(self, payload: wire.Draft) -> MailDraft:
        """Rebuild a draft, fencing subject and body."""
        return MailDraft(
            draft_id=payload.draft_id,
            to=tuple(EmailAddress(value=item) for item in payload.to),
            cc=tuple(EmailAddress(value=item) for item in payload.cc),
            subject=untrusted(payload.subject, UntrustedOrigin.MAIL_SUBJECT),
            body=untrusted(payload.body, UntrustedOrigin.MAIL_BODY),
            in_reply_to_message_id=payload.in_reply_to_message_id,
            thread_id=payload.thread_id,
        )

    def to_wire(self, draft: MailDraft) -> wire.Draft:
        """Project a draft onto the wire, so a server can store or send it."""
        return wire.Draft(
            draft_id=draft.draft_id,
            to=tuple(address.value for address in draft.to),
            cc=tuple(address.value for address in draft.cc),
            subject=draft.subject.expose(),
            body=draft.body.expose(),
            in_reply_to_message_id=draft.in_reply_to_message_id,
            thread_id=draft.thread_id,
        )
