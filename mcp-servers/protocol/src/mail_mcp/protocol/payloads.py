"""Shapes carried on the wire.

Plain JSON types only: text, numbers, booleans and timestamps. No domain model,
no untrusted-content wrapper, no security metadata. A server fills these in; a
caller decides what they mean.

Free text stays plain text here on purpose. Treating it as untrusted is the
caller's responsibility, and a server has no way of knowing what a caller will
do with it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Importance(StrEnum):
    """How urgent the sender said a message was."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class SortOrder(StrEnum):
    """Ordering applied to search results."""

    NEWEST_FIRST = "NEWEST_FIRST"
    OLDEST_FIRST = "OLDEST_FIRST"


class Payload(BaseModel):
    """Base class for the shapes crossing the boundary.

    Unknown fields are ignored rather than refused, so a server may add one
    without breaking every caller at once.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")


class Participant(Payload):
    """Somebody taking part in a conversation."""

    address: str
    display_name: str | None = None


class Attachment(Payload):
    """Attachment metadata. Never the bytes."""

    attachment_id: str
    file_name: str
    media_type: str
    size_bytes: int = Field(ge=0)


class Label(Payload):
    """A label or folder organising a mailbox."""

    label_id: str
    name: str
    is_system: bool = False


class Header(Payload):
    """A search hit. Never carries a body."""

    message_id: str
    thread_id: str
    subject: str
    sender: Participant
    recipient_count: int = Field(ge=0)
    sent_at: datetime
    is_read: bool
    is_archived: bool = False
    has_attachments: bool = False
    importance: Importance = Importance.NORMAL
    label_ids: tuple[str, ...] = ()


class Message(Payload):
    """A complete message, body included."""

    message_id: str
    thread_id: str
    subject: str
    body: str
    sender: Participant
    to: tuple[Participant, ...] = ()
    cc: tuple[Participant, ...] = ()
    sent_at: datetime
    is_read: bool
    is_archived: bool = False
    importance: Importance = Importance.NORMAL
    label_ids: tuple[str, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    in_reply_to: str | None = None


class Thread(Payload):
    """A conversation."""

    thread_id: str
    subject: str
    messages: tuple[Message, ...] = Field(min_length=1)


class SearchResult(Payload):
    """The outcome of a mailbox query."""

    headers: tuple[Header, ...] = ()
    total_count: int = Field(ge=0)
    truncated: bool = False


class Draft(Payload):
    """A prepared message that has not been sent."""

    draft_id: str | None = None
    to: tuple[str, ...] = Field(min_length=1)
    cc: tuple[str, ...] = ()
    subject: str
    body: str
    in_reply_to_message_id: str | None = None
    thread_id: str | None = None


class SendResult(Payload):
    """The outcome of a delivery."""

    message_id: str
    thread_id: str | None = None
    sent_at: datetime


class Labels(Payload):
    """The labels of a mailbox."""

    labels: tuple[Label, ...] = ()
