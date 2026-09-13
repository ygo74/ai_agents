"""Shapes the official Gmail MCP server returns.

Transcribed from the schemas recorded by
``python -m ai_agent_lab.mail.application.discover --server gmail`` and kept
in ``docs/mcp-discovery/gmail-tools.json``. Every field the server declares as
optional is optional here, so a message missing a subject or a date is data to
handle rather than a crash.

Reading state and archiving are not fields: Gmail expresses them as labels, and
``UNREAD`` and ``INBOX`` are read back the same way they are written.
"""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from ygo74.agent_runtime.domains.security.untrusted import untrusted

from ai_agent_lab.mail.domain.models import (
    EmailAddress,
    MailAttachment,
    MailHeader,
    MailLabel,
    MailMessage,
    MailParticipant,
)
from ai_agent_lab.mail.domain.origins import MailOrigin
from ai_agent_lab.mail.mail_errors import MailToolProtocolError

UNREAD_LABEL = "UNREAD"
INBOX_LABEL = "INBOX"
_SYSTEM_LABEL = "SYSTEM"
_logger = logging.getLogger(__name__)


class GmailPayload(BaseModel):
    """Base class for the shapes the Gmail server returns."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class GmailAttachment(GmailPayload):
    """Attachment metadata, without the bytes."""

    attachment_id: str = Field(default="", alias="id")
    filename: str = ""
    mime_type: str = Field(default="application/octet-stream", alias="mimeType")

    def to_domain(self) -> MailAttachment:
        """Rebuild the domain attachment, fencing the file name.

        Gmail reports no size at this level, and the agent never needs one, so
        it is left at zero rather than guessed.
        """
        _logger.debug(
            "GmailAttachment.to_domain arguments: attachment_id=%s, filename_length=%d, mime_type=%s",
            self.attachment_id,
            len(self.filename),
            self.mime_type,
        )
        return MailAttachment(
            attachment_id=self.attachment_id,
            file_name=untrusted(self.filename, MailOrigin.ATTACHMENT_NAME),
            media_type=self.mime_type or "application/octet-stream",
            size_bytes=0,
        )


class GmailMessage(GmailPayload):
    """A message as the Gmail server returns it."""

    message_id: str = Field(default="", alias="id")
    thread_id: str = Field(default="", alias="threadId")
    subject: str = ""
    sender: str = ""
    to_recipients: tuple[str, ...] = Field(default=(), alias="toRecipients")
    cc_recipients: tuple[str, ...] = Field(default=(), alias="ccRecipients")
    date: datetime | None = None
    label_ids: tuple[str, ...] = Field(default=(), alias="labelIds")
    plaintext_body: str = Field(default="", alias="plaintextBody")
    snippet: str = ""
    attachments: tuple[GmailAttachment, ...] = ()
    attachment_ids: tuple[str, ...] = Field(default=(), alias="attachmentIds")

    @property
    def is_read(self) -> bool:
        """Whether Gmail no longer marks the message unread."""
        return UNREAD_LABEL not in self.label_ids

    @property
    def is_archived(self) -> bool:
        """Whether the message left the inbox."""
        return INBOX_LABEL not in self.label_ids

    @property
    def has_attachments(self) -> bool:
        """Whether the message carries at least one attachment."""
        return bool(self.attachments or self.attachment_ids)

    @property
    def sent_at(self) -> datetime:
        """Return when the message was sent.

        A message without a date cannot be ordered, dated or reasoned about, so
        a missing one is reported rather than replaced by a placeholder.
        """
        if self.date is None:
            raise MailToolProtocolError(f"message {self.message_id!r} was returned without a date")
        return self.date

    def to_domain(self, fallback_thread_id: str = "") -> MailMessage:
        """Rebuild the domain message, fencing subject and body."""
        _logger.debug(
            "GmailMessage.to_domain arguments: message_id=%s, thread_id=%s, "
            "fallback_thread_id=%s, subject_length=%d, body_length=%d, "
            "to_count=%d, cc_count=%d, attachments=%d",
            self.message_id,
            self.thread_id,
            fallback_thread_id,
            len(self.subject),
            len(self.plaintext_body or self.snippet),
            len(self.to_recipients),
            len(self.cc_recipients),
            len(self.attachments),
        )
        return MailMessage(
            message_id=self.message_id,
            thread_id=self.thread_id or fallback_thread_id,
            subject=untrusted(self.subject, MailOrigin.SUBJECT),
            body=untrusted(self.plaintext_body or self.snippet, MailOrigin.BODY),
            sender=parse_participant(self.sender),
            to=tuple(parse_participant(item) for item in self.to_recipients),
            cc=tuple(parse_participant(item) for item in self.cc_recipients),
            sent_at=self.sent_at,
            is_read=self.is_read,
            is_archived=self.is_archived,
            label_ids=self.label_ids,
            attachments=tuple(item.to_domain() for item in self.attachments),
        )

    def to_header(self, fallback_thread_id: str = "") -> MailHeader:
        """Project the message onto a search preview, without its body."""
        _logger.debug(
            "GmailMessage.to_header arguments: message_id=%s, thread_id=%s, "
            "fallback_thread_id=%s, subject_length=%d, recipient_count=%d",
            self.message_id,
            self.thread_id,
            fallback_thread_id,
            len(self.subject),
            len(self.to_recipients) + len(self.cc_recipients),
        )
        return MailHeader(
            message_id=self.message_id,
            thread_id=self.thread_id or fallback_thread_id,
            subject=untrusted(self.subject, MailOrigin.SUBJECT),
            sender=parse_participant(self.sender),
            recipient_count=len(self.to_recipients) + len(self.cc_recipients),
            sent_at=self.sent_at,
            is_read=self.is_read,
            is_archived=self.is_archived,
            has_attachments=self.has_attachments,
            label_ids=self.label_ids,
        )


class GmailThread(GmailPayload):
    """A conversation as the Gmail server returns it."""

    thread_id: str = Field(default="", alias="id")
    messages: tuple[GmailMessage, ...] = ()


class GmailThreadList(GmailPayload):
    """The outcome of a thread search."""

    threads: tuple[GmailThread, ...] = ()
    next_page_token: str = Field(default="", alias="nextPageToken")
    result_count_estimate: str = Field(default="", alias="resultCountEstimate")

    @property
    def estimated_total(self) -> int:
        """Return the estimate Gmail reported, which it sends as text."""
        try:
            return int(self.result_count_estimate)
        except ValueError:
            return 0


class GmailLabel(GmailPayload):
    """A label as the Gmail server returns it."""

    label_id: str = Field(default="", alias="labelId")
    name: str = ""
    label_type: str = Field(default="", alias="labelType")

    def to_domain(self) -> MailLabel:
        """Rebuild the domain label, fencing its name."""
        _logger.debug(
            "GmailLabel.to_domain arguments: label_id=%s, name_length=%d, label_type=%s",
            self.label_id,
            len(self.name),
            self.label_type,
        )
        return MailLabel(
            label_id=self.label_id,
            name=untrusted(self.name, MailOrigin.LABEL),
            is_system=self.label_type == _SYSTEM_LABEL,
        )


class GmailLabelList(GmailPayload):
    """The labels of the mailbox."""

    labels: tuple[GmailLabel, ...] = ()


class GmailDraft(GmailPayload):
    """A draft as the Gmail server returns it."""

    draft_id: str = Field(default="", alias="id")
    message_id: str = Field(default="", alias="messageId")
    thread_id: str = Field(default="", alias="threadId")


def parse_participant(value: str) -> MailParticipant:
    """Read a participant out of an address header.

    Gmail returns a single string, which may carry a display name. The name is
    chosen by the sender, so it is fenced as untrusted content.
    """
    text = value.strip()
    name, address = _split_address(text)
    return MailParticipant(
        address=EmailAddress(value=address),
        display_name=untrusted(name, MailOrigin.SENDER_NAME) if name else None,
    )


def _split_address(text: str) -> tuple[str, str]:
    """Split ``Name <address>`` into its two parts."""
    if not text.endswith(">") or "<" not in text:
        return "", text
    name, _, remainder = text.partition("<")
    return name.strip().strip('"'), remainder[:-1].strip()
