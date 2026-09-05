"""Typed models of the mail domain.

These models are the vocabulary shared by skills, MCP contracts and framework
adapters. They carry no infrastructure knowledge: nothing here is aware of
Gmail, IMAP, SMTP, OAuth or of any agent framework.

Text produced by third parties (subjects, bodies, display names, label names)
is wrapped in :class:`~ai_agent_lab.domain.security.untrusted.UntrustedText`
so that it can never be silently treated as an instruction.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_agent_lab.domain.mail.enums import (
    ActionOrigin,
    ConfidenceLevel,
    MailCategory,
    MailImportance,
    MailSortOrder,
)
from ai_agent_lab.domain.security.untrusted import UntrustedText

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
_MAX_SEARCH_LIMIT = 100


class DomainModel(BaseModel):
    """Base class for immutable, strictly validated domain models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_timezone(value: datetime) -> datetime:
    """Normalise a datetime to UTC and reject naive values."""
    if value.tzinfo is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


class EmailAddress(DomainModel):
    """A normalised mailbox address."""

    value: str

    @field_validator("value")
    @classmethod
    def _validate(cls, value: str) -> str:
        normalised = value.strip().lower()
        if not _EMAIL_PATTERN.match(normalised):
            raise ValueError(f"invalid email address: {value!r}")
        return normalised

    @property
    def domain(self) -> str:
        """Domain part of the address."""
        return self.value.split("@", 1)[1]

    def __str__(self) -> str:
        """Return the normalised address."""
        return self.value


class MailParticipant(DomainModel):
    """A person taking part in a conversation.

    The display name is chosen by the sender and is therefore untrusted.
    """

    address: EmailAddress
    display_name: UntrustedText | None = None


class MailAttachment(DomainModel):
    """Metadata of an attachment.

    The binary content is deliberately absent: the mail agent never needs it,
    and not carrying it is the simplest form of data minimisation.
    """

    attachment_id: str
    file_name: UntrustedText
    media_type: str
    size_bytes: int = Field(ge=0)


class MailLabel(DomainModel):
    """A label or folder used to organise a mailbox."""

    label_id: str
    name: UntrustedText
    is_system: bool = False


class MailHeader(DomainModel):
    """Lightweight preview of a message, as returned by a search.

    Search returns headers rather than full messages so that a broad query does
    not pull entire bodies into the context window.
    """

    message_id: str
    thread_id: str
    subject: UntrustedText
    sender: MailParticipant
    recipient_count: int = Field(ge=0)
    sent_at: datetime
    is_read: bool
    is_archived: bool = False
    has_attachments: bool = False
    importance: MailImportance = MailImportance.NORMAL
    label_ids: tuple[str, ...] = ()

    _normalise_sent_at = field_validator("sent_at")(_require_timezone)


class MailMessage(DomainModel):
    """A complete message, body included."""

    message_id: str
    thread_id: str
    subject: UntrustedText
    body: UntrustedText
    sender: MailParticipant
    to: tuple[MailParticipant, ...] = ()
    cc: tuple[MailParticipant, ...] = ()
    sent_at: datetime
    is_read: bool
    is_archived: bool = False
    importance: MailImportance = MailImportance.NORMAL
    label_ids: tuple[str, ...] = ()
    attachments: tuple[MailAttachment, ...] = ()
    in_reply_to: str | None = None

    _normalise_sent_at = field_validator("sent_at")(_require_timezone)

    @property
    def has_attachments(self) -> bool:
        """Whether the message carries at least one attachment."""
        return bool(self.attachments)

    def to_header(self) -> MailHeader:
        """Project the message onto its lightweight preview."""
        return MailHeader(
            message_id=self.message_id,
            thread_id=self.thread_id,
            subject=self.subject,
            sender=self.sender,
            recipient_count=len(self.to) + len(self.cc),
            sent_at=self.sent_at,
            is_read=self.is_read,
            is_archived=self.is_archived,
            has_attachments=self.has_attachments,
            importance=self.importance,
            label_ids=self.label_ids,
        )


class MailThread(DomainModel):
    """A conversation: an ordered set of related messages."""

    thread_id: str
    subject: UntrustedText
    messages: tuple[MailMessage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_consistency(self) -> MailThread:
        foreign = [m.message_id for m in self.messages if m.thread_id != self.thread_id]
        if foreign:
            raise ValueError(f"messages {foreign} do not belong to thread {self.thread_id!r}")
        return self

    @property
    def participants(self) -> tuple[MailParticipant, ...]:
        """Distinct participants, in order of first appearance."""
        seen: dict[str, MailParticipant] = {}
        for message in self.messages:
            for participant in (message.sender, *message.to, *message.cc):
                seen.setdefault(participant.address.value, participant)
        return tuple(seen.values())

    @property
    def latest_message(self) -> MailMessage:
        """Most recent message of the conversation."""
        return max(self.messages, key=lambda message: message.sent_at)

    def in_chronological_order(self) -> tuple[MailMessage, ...]:
        """Messages sorted from oldest to newest."""
        return tuple(sorted(self.messages, key=lambda message: message.sent_at))


class MailSearchRequest(DomainModel):
    """A structured mailbox query.

    A single generic search request covers every search variation (by sender,
    recipient, subject, date range, keyword, unread state or any combination),
    which is why the MCP surface exposes one search tool rather than many.
    """

    keywords: str | None = None
    sender: EmailAddress | None = None
    recipient: EmailAddress | None = None
    subject_contains: str | None = None
    label_ids: tuple[str, ...] = ()
    date_from: datetime | None = None
    date_to: datetime | None = None
    unread_only: bool = False
    has_attachments: bool | None = None
    limit: int = Field(default=20, ge=1, le=_MAX_SEARCH_LIMIT)
    sort_order: MailSortOrder = MailSortOrder.NEWEST_FIRST

    @field_validator("date_from", "date_to")
    @classmethod
    def _normalise_bounds(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_timezone(value)

    @model_validator(mode="after")
    def _validate_range(self) -> MailSearchRequest:
        if self.date_from is not None and self.date_to is not None and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self

    @property
    def is_empty(self) -> bool:
        """Whether the request carries no discriminating criterion."""
        return not any(
            (
                self.keywords,
                self.sender,
                self.recipient,
                self.subject_contains,
                self.label_ids,
                self.date_from,
                self.date_to,
                self.unread_only,
                self.has_attachments is not None,
            )
        )


class MailSearchResult(DomainModel):
    """Outcome of a mailbox query."""

    headers: tuple[MailHeader, ...] = ()
    total_count: int = Field(ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def _validate_count(self) -> MailSearchResult:
        if self.total_count < len(self.headers):
            raise ValueError("total_count cannot be smaller than the number of returned headers")
        return self


class MailDraft(DomainModel):
    """A prepared message that has not been sent.

    A draft is produced by reasoning over untrusted content, so its subject and
    body stay untrusted until a human approves them.
    """

    draft_id: str | None = None
    to: tuple[EmailAddress, ...] = Field(min_length=1)
    cc: tuple[EmailAddress, ...] = ()
    subject: UntrustedText
    body: UntrustedText
    in_reply_to_message_id: str | None = None
    thread_id: str | None = None

    @property
    def recipients(self) -> tuple[EmailAddress, ...]:
        """Every address the message would reach."""
        return (*self.to, *self.cc)


class MailSendRequest(DomainModel):
    """Instruction to send a previously prepared draft."""

    draft: MailDraft


class MailSendResult(DomainModel):
    """Outcome of a send operation."""

    message_id: str
    thread_id: str | None = None
    sent_at: datetime

    _normalise_sent_at = field_validator("sent_at")(_require_timezone)


class MailSourceReference(DomainModel):
    """Pointer to the message that grounds a piece of analysis."""

    message_id: str
    thread_id: str | None = None


class MailClassification(DomainModel):
    """Category assigned to a single message."""

    message_id: str
    category: MailCategory
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=280)


class MailAction(DomainModel):
    """An action the mailbox owner is expected to perform."""

    description: str
    origin: ActionOrigin
    confidence: ConfidenceLevel
    source: MailSourceReference
    due_date: datetime | None = None

    @field_validator("due_date")
    @classmethod
    def _normalise_due_date(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_timezone(value)

    @property
    def is_factual(self) -> bool:
        """Whether the action was explicitly stated rather than deduced."""
        return self.origin is ActionOrigin.EXPLICIT


class MailSummary(DomainModel):
    """Structured summary of a message, a thread or a set of messages.

    Facts, inferences and open questions are kept apart so that deduced
    information is never presented as established.
    """

    summary: str
    key_points: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    actions: tuple[MailAction, ...] = ()
    deadlines: tuple[datetime, ...] = ()
    participants: tuple[EmailAddress, ...] = ()
    uncertainties: tuple[str, ...] = ()
    sources: tuple[MailSourceReference, ...] = ()

    @field_validator("deadlines")
    @classmethod
    def _normalise_deadlines(cls, value: tuple[datetime, ...]) -> tuple[datetime, ...]:
        return tuple(_require_timezone(item) for item in value)
