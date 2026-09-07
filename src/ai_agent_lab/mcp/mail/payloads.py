"""Wire format of the mail MCP tools.

This is the payload contract: what a mail MCP server sends back and what a
client is allowed to expect. It is expressed as validated models rather than as
free-form dictionaries, because everything crossing this boundary comes from
outside the application and must be checked before it becomes a domain object.

Free text arrives as plain strings and is wrapped as
:class:`~ai_agent_lab.domain.security.untrusted.UntrustedText` on the way in.
That wrapping happens here, once, so no caller can forget it.

A server implementing this format - the reference server, a server built on EWS
or on Microsoft Graph - needs no adapter at all. A server that speaks its own
shapes, such as the official Gmail one, is reconciled by a dialect.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.domain.mail.enums import MailImportance
from ai_agent_lab.domain.mail.models import (
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
from ai_agent_lab.domain.security.untrusted import UntrustedOrigin, untrusted


class Payload(BaseModel):
    """Base class for the shapes crossing the mail MCP boundary."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class ParticipantPayload(Payload):
    """A participant, as carried on the wire."""

    address: str
    display_name: str | None = None

    def to_domain(self) -> MailParticipant:
        """Rebuild the domain participant, fencing the display name."""
        return MailParticipant(
            address=EmailAddress(value=self.address),
            display_name=(
                None if self.display_name is None else untrusted(self.display_name, UntrustedOrigin.MAIL_SENDER_NAME)
            ),
        )

    @classmethod
    def of(cls, participant: MailParticipant) -> ParticipantPayload:
        """Project a domain participant onto the wire."""
        return cls(
            address=participant.address.value,
            display_name=None if participant.display_name is None else participant.display_name.expose(),
        )


class AttachmentPayload(Payload):
    """Attachment metadata, as carried on the wire. Never the bytes."""

    attachment_id: str
    file_name: str
    media_type: str
    size_bytes: int = Field(ge=0)

    def to_domain(self) -> MailAttachment:
        """Rebuild the domain attachment, fencing the file name."""
        return MailAttachment(
            attachment_id=self.attachment_id,
            file_name=untrusted(self.file_name, UntrustedOrigin.MAIL_ATTACHMENT_NAME),
            media_type=self.media_type,
            size_bytes=self.size_bytes,
        )

    @classmethod
    def of(cls, attachment: MailAttachment) -> AttachmentPayload:
        """Project a domain attachment onto the wire."""
        return cls(
            attachment_id=attachment.attachment_id,
            file_name=attachment.file_name.expose(),
            media_type=attachment.media_type,
            size_bytes=attachment.size_bytes,
        )


class LabelPayload(Payload):
    """A label, as carried on the wire."""

    label_id: str
    name: str
    is_system: bool = False

    def to_domain(self) -> MailLabel:
        """Rebuild the domain label, fencing its name."""
        return MailLabel(
            label_id=self.label_id,
            name=untrusted(self.name, UntrustedOrigin.MAIL_LABEL),
            is_system=self.is_system,
        )

    @classmethod
    def of(cls, label: MailLabel) -> LabelPayload:
        """Project a domain label onto the wire."""
        return cls(label_id=label.label_id, name=label.name.expose(), is_system=label.is_system)


class HeaderPayload(Payload):
    """A search hit, as carried on the wire. Never a body."""

    message_id: str
    thread_id: str
    subject: str
    sender: ParticipantPayload
    recipient_count: int = Field(ge=0)
    sent_at: datetime
    is_read: bool
    is_archived: bool = False
    has_attachments: bool = False
    importance: MailImportance = MailImportance.NORMAL
    label_ids: tuple[str, ...] = ()

    def to_domain(self) -> MailHeader:
        """Rebuild the domain header, fencing the subject."""
        return MailHeader(
            message_id=self.message_id,
            thread_id=self.thread_id,
            subject=untrusted(self.subject, UntrustedOrigin.MAIL_SUBJECT),
            sender=self.sender.to_domain(),
            recipient_count=self.recipient_count,
            sent_at=self.sent_at,
            is_read=self.is_read,
            is_archived=self.is_archived,
            has_attachments=self.has_attachments,
            importance=self.importance,
            label_ids=self.label_ids,
        )

    @classmethod
    def of(cls, header: MailHeader) -> HeaderPayload:
        """Project a domain header onto the wire."""
        return cls(
            message_id=header.message_id,
            thread_id=header.thread_id,
            subject=header.subject.expose(),
            sender=ParticipantPayload.of(header.sender),
            recipient_count=header.recipient_count,
            sent_at=header.sent_at,
            is_read=header.is_read,
            is_archived=header.is_archived,
            has_attachments=header.has_attachments,
            importance=header.importance,
            label_ids=header.label_ids,
        )


class MessagePayload(Payload):
    """A complete message, as carried on the wire."""

    message_id: str
    thread_id: str
    subject: str
    body: str
    sender: ParticipantPayload
    to: tuple[ParticipantPayload, ...] = ()
    cc: tuple[ParticipantPayload, ...] = ()
    sent_at: datetime
    is_read: bool
    is_archived: bool = False
    importance: MailImportance = MailImportance.NORMAL
    label_ids: tuple[str, ...] = ()
    attachments: tuple[AttachmentPayload, ...] = ()
    in_reply_to: str | None = None

    def to_domain(self) -> MailMessage:
        """Rebuild the domain message, fencing subject and body."""
        return MailMessage(
            message_id=self.message_id,
            thread_id=self.thread_id,
            subject=untrusted(self.subject, UntrustedOrigin.MAIL_SUBJECT),
            body=untrusted(self.body, UntrustedOrigin.MAIL_BODY),
            sender=self.sender.to_domain(),
            to=tuple(item.to_domain() for item in self.to),
            cc=tuple(item.to_domain() for item in self.cc),
            sent_at=self.sent_at,
            is_read=self.is_read,
            is_archived=self.is_archived,
            importance=self.importance,
            label_ids=self.label_ids,
            attachments=tuple(item.to_domain() for item in self.attachments),
            in_reply_to=self.in_reply_to,
        )

    @classmethod
    def of(cls, message: MailMessage) -> MessagePayload:
        """Project a domain message onto the wire."""
        return cls(
            message_id=message.message_id,
            thread_id=message.thread_id,
            subject=message.subject.expose(),
            body=message.body.expose(),
            sender=ParticipantPayload.of(message.sender),
            to=tuple(ParticipantPayload.of(item) for item in message.to),
            cc=tuple(ParticipantPayload.of(item) for item in message.cc),
            sent_at=message.sent_at,
            is_read=message.is_read,
            is_archived=message.is_archived,
            importance=message.importance,
            label_ids=message.label_ids,
            attachments=tuple(AttachmentPayload.of(item) for item in message.attachments),
            in_reply_to=message.in_reply_to,
        )


class ThreadPayload(Payload):
    """A conversation, as carried on the wire."""

    thread_id: str
    subject: str
    messages: tuple[MessagePayload, ...] = Field(min_length=1)

    def to_domain(self) -> MailThread:
        """Rebuild the domain conversation."""
        return MailThread(
            thread_id=self.thread_id,
            subject=untrusted(self.subject, UntrustedOrigin.MAIL_SUBJECT),
            messages=tuple(message.to_domain() for message in self.messages),
        )

    @classmethod
    def of(cls, thread: MailThread) -> ThreadPayload:
        """Project a domain conversation onto the wire."""
        return cls(
            thread_id=thread.thread_id,
            subject=thread.subject.expose(),
            messages=tuple(MessagePayload.of(message) for message in thread.messages),
        )


class SearchResultPayload(Payload):
    """The outcome of a query, as carried on the wire."""

    headers: tuple[HeaderPayload, ...] = ()
    total_count: int = Field(ge=0)
    truncated: bool = False

    def to_domain(self) -> MailSearchResult:
        """Rebuild the domain search result."""
        return MailSearchResult(
            headers=tuple(header.to_domain() for header in self.headers),
            total_count=self.total_count,
            truncated=self.truncated,
        )

    @classmethod
    def of(cls, result: MailSearchResult) -> SearchResultPayload:
        """Project a domain search result onto the wire."""
        return cls(
            headers=tuple(HeaderPayload.of(header) for header in result.headers),
            total_count=result.total_count,
            truncated=result.truncated,
        )


class DraftPayload(Payload):
    """A prepared message, as carried on the wire."""

    draft_id: str | None = None
    to: tuple[str, ...] = Field(min_length=1)
    cc: tuple[str, ...] = ()
    subject: str
    body: str
    in_reply_to_message_id: str | None = None
    thread_id: str | None = None

    def to_domain(self) -> MailDraft:
        """Rebuild the domain draft, fencing subject and body."""
        return MailDraft(
            draft_id=self.draft_id,
            to=tuple(EmailAddress(value=item) for item in self.to),
            cc=tuple(EmailAddress(value=item) for item in self.cc),
            subject=untrusted(self.subject, UntrustedOrigin.MAIL_SUBJECT),
            body=untrusted(self.body, UntrustedOrigin.MAIL_BODY),
            in_reply_to_message_id=self.in_reply_to_message_id,
            thread_id=self.thread_id,
        )

    @classmethod
    def of(cls, draft: MailDraft) -> DraftPayload:
        """Project a domain draft onto the wire."""
        return cls(
            draft_id=draft.draft_id,
            to=tuple(address.value for address in draft.to),
            cc=tuple(address.value for address in draft.cc),
            subject=draft.subject.expose(),
            body=draft.body.expose(),
            in_reply_to_message_id=draft.in_reply_to_message_id,
            thread_id=draft.thread_id,
        )


class SendResultPayload(Payload):
    """The outcome of a delivery, as carried on the wire."""

    message_id: str
    thread_id: str | None = None
    sent_at: datetime

    def to_domain(self) -> MailSendResult:
        """Rebuild the domain send result."""
        return MailSendResult(message_id=self.message_id, thread_id=self.thread_id, sent_at=self.sent_at)

    @classmethod
    def of(cls, result: MailSendResult) -> SendResultPayload:
        """Project a domain send result onto the wire."""
        return cls(message_id=result.message_id, thread_id=result.thread_id, sent_at=result.sent_at)


class LabelsPayload(Payload):
    """The labels of a mailbox, as carried on the wire."""

    labels: tuple[LabelPayload, ...] = ()

    def to_domain(self) -> tuple[MailLabel, ...]:
        """Rebuild the domain labels."""
        return tuple(label.to_domain() for label in self.labels)

    @classmethod
    def of(cls, labels: tuple[MailLabel, ...]) -> LabelsPayload:
        """Project domain labels onto the wire."""
        return cls(labels=tuple(LabelPayload.of(label) for label in labels))
