"""Input schemas of the capabilities exposed by the Mail Agent.

These models are what a language model fills in when it selects a tool. They
are deliberately narrow: identifiers, flags and a stated intent. A model never
supplies recipients or a message body directly - those come from a draft
prepared in an earlier turn and retrieved by reference.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.domain.mail.enums import MailSortOrder

_MAX_RESULTS = 50


class MailToolInput(BaseModel):
    """Base class for the tool inputs of the Mail Agent."""

    model_config = ConfigDict(extra="forbid")


class SearchMailInput(MailToolInput):
    """Criteria of a mailbox search."""

    keywords: str | None = Field(default=None, description="Free text that must appear in the subject or the body.")
    sender: str | None = Field(default=None, description="Email address of the sender.")
    recipient: str | None = Field(default=None, description="Email address of a recipient.")
    subject_contains: str | None = Field(default=None, description="Text that must appear in the subject.")
    label_ids: list[str] = Field(default_factory=list, description="Restrict to messages carrying any of these labels.")
    date_from: str | None = Field(default=None, description="ISO-8601 lower bound of the sent date, inclusive.")
    date_to: str | None = Field(default=None, description="ISO-8601 upper bound of the sent date, inclusive.")
    unread_only: bool = Field(default=False, description="Keep only unread messages.")
    has_attachments: bool | None = Field(default=None, description="Filter on the presence of attachments.")
    limit: int = Field(default=20, ge=1, le=_MAX_RESULTS, description="Maximum number of results.")
    sort_order: MailSortOrder = Field(default=MailSortOrder.NEWEST_FIRST, description="Ordering of the results.")


class MessageInput(MailToolInput):
    """Designation of a single message."""

    message_id: str = Field(description="Identifier of the message, as returned by a search.")


class ThreadInput(MailToolInput):
    """Designation of a conversation."""

    thread_id: str = Field(description="Identifier of the conversation, as returned by a search.")


class MessageOrThreadInput(MailToolInput):
    """Designation of a message or of a whole conversation."""

    message_id: str | None = Field(default=None, description="Identifier of a single message.")
    thread_id: str | None = Field(default=None, description="Identifier of a conversation.")


class ClassifyMailInput(MailToolInput):
    """Messages to classify."""

    message_ids: list[str] = Field(description="Identifiers of the messages to classify.", min_length=1)


class ExtractActionsInput(MailToolInput):
    """Scope of an action extraction."""

    message_ids: list[str] = Field(default_factory=list, description="Identifiers of the messages to analyse.")
    thread_id: str | None = Field(default=None, description="Analyse a whole conversation instead.")
    explicit_only: bool = Field(default=False, description="Keep only actions the messages state explicitly.")


class DraftReplyInput(MailToolInput):
    """Instruction to prepare a reply."""

    message_id: str | None = Field(default=None, description="Message to reply to.")
    thread_id: str | None = Field(default=None, description="Conversation to reply to, most recent message.")
    intent: str = Field(description="What the mailbox owner wants to say, in their own words.", min_length=1)
    reply_all: bool = Field(default=False, description="Keep the other participants in copy.")


class DraftReferenceInput(MailToolInput):
    """Designation of a draft prepared in an earlier turn."""

    draft_reference: str = Field(description="Reference returned when the draft was prepared.")


class SetReadStateInput(MailToolInput):
    """Change of the read state of a message."""

    message_id: str = Field(description="Identifier of the message.")
    is_read: bool = Field(description="True to mark as read, False to mark as unread.")


class LabelInput(MailToolInput):
    """Designation of a label applied to a message."""

    message_id: str = Field(description="Identifier of the message.")
    label_id: str = Field(description="Identifier of the label, as returned by the label listing.")


class NoInput(MailToolInput):
    """Input of a capability that takes no argument."""
