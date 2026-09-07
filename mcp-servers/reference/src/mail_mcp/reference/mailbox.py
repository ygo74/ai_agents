"""A mailbox held in memory, loaded from a JSON dataset.

The dataset is written in the protocol shapes, so loading it is a validation and
nothing more. Search has to be reimplemented here because a real server delegates
it to the mail system, and this one has no mail system behind it.

State changes are kept in memory for the lifetime of the process: a conversation
sees its own effect, and the next run starts clean.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mail_mcp.protocol import payloads as wire
from mail_mcp.protocol.errors import AccessDeniedError, NotFoundError, ProtocolError
from mail_mcp.protocol.rules import require_deletable


class InMemoryMailbox:
    """One mailbox served from validated protocol payloads."""

    def __init__(self, messages: Sequence[wire.Message], labels: Sequence[wire.Label]) -> None:
        self._messages = {message.message_id: message for message in messages}
        self._labels = tuple(labels)
        self._drafts: dict[str, wire.Draft] = {}
        self._sent: list[wire.SendResult] = []

    @property
    def sent(self) -> tuple[wire.SendResult, ...]:
        """What has been delivered, so a test can assert on it."""
        return tuple(self._sent)

    async def search(
        self,
        *,
        keywords: str | None = None,
        sender: str | None = None,
        recipient: str | None = None,
        subject_contains: str | None = None,
        label_ids: Sequence[str] = (),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        unread_only: bool = False,
        has_attachments: bool | None = None,
        limit: int = 20,
        sort_order: wire.SortOrder = wire.SortOrder.NEWEST_FIRST,
    ) -> wire.SearchResult:
        """Return the message headers matching a query."""
        query = _Query(
            keywords=keywords,
            sender=sender,
            recipient=recipient,
            subject_contains=subject_contains,
            label_ids=tuple(label_ids),
            date_from=date_from,
            date_to=date_to,
            unread_only=unread_only,
            has_attachments=has_attachments,
        )
        matching = [message for message in self._messages.values() if query.matches(message)]
        matching.sort(key=lambda message: message.sent_at, reverse=sort_order is wire.SortOrder.NEWEST_FIRST)
        page = tuple(_header_of(message) for message in matching[:limit])
        return wire.SearchResult(headers=page, total_count=len(matching), truncated=len(matching) > len(page))

    async def get_message(self, message_id: str) -> wire.Message:
        """Return one complete message."""
        return self._require(message_id)

    async def get_thread(self, thread_id: str) -> wire.Thread:
        """Return every message of a conversation, oldest first."""
        messages = tuple(
            sorted(
                (message for message in self._messages.values() if message.thread_id == thread_id),
                key=lambda message: message.sent_at,
            )
        )
        if not messages:
            raise NotFoundError("thread", thread_id)
        return wire.Thread(thread_id=thread_id, subject=messages[0].subject, messages=messages)

    async def list_labels(self) -> wire.Labels:
        """Return the labels available in the mailbox."""
        return wire.Labels(labels=self._labels)

    async def create_label(self, name: str) -> wire.CreatedLabel:
        """Make a label exist, returning whether it had to be created."""
        existing = self._label_named(name)
        if existing is not None:
            return wire.CreatedLabel(label=existing, created=False)
        label = wire.Label(label_id=self._mint(name), name=name, is_system=False)
        self._labels = (*self._labels, label)
        return wire.CreatedLabel(label=label, created=True)

    async def delete_label(self, label_id: str) -> None:
        """Delete a label, detaching it from every message carrying it.

        The detachment is the part worth reproducing: a caller that deleted a
        label here and found messages still carrying it would be testing
        against a mailbox no real one behaves like.
        """
        require_deletable(self._require_label(label_id))
        self._labels = tuple(label for label in self._labels if label.label_id != label_id)
        for message in list(self._messages.values()):
            if label_id in message.label_ids:
                self._replace(message.model_copy(update={"label_ids": _without(message.label_ids, label_id)}))

    async def create_draft(self, draft: wire.Draft) -> wire.Draft:
        """Persist a draft without delivering anything."""
        stored = draft.model_copy(update={"draft_id": draft.draft_id or f"draft-{uuid.uuid4().hex[:8]}"})
        self._drafts[str(stored.draft_id)] = stored
        return stored

    async def send(self, draft: wire.Draft) -> wire.SendResult:
        """Record a delivery. Nothing leaves this process."""
        result = wire.SendResult(
            message_id=f"sent-{uuid.uuid4().hex[:8]}",
            thread_id=draft.thread_id,
            sent_at=datetime.now(UTC),
        )
        self._sent.append(result)
        return result

    async def set_read_state(self, message_id: str, is_read: bool) -> None:
        """Mark a message as read or unread."""
        self._replace(self._require(message_id).model_copy(update={"is_read": is_read}))

    async def archive(self, message_id: str) -> None:
        """Remove a message from the inbox without deleting it."""
        self._replace(self._require(message_id).model_copy(update={"is_archived": True}))

    async def apply_label(self, message_id: str, label_id: str) -> None:
        """Attach a label to a message."""
        self._require_label(label_id)
        message = self._require(message_id)
        if label_id in message.label_ids:
            return
        self._replace(message.model_copy(update={"label_ids": (*message.label_ids, label_id)}))

    async def remove_label(self, message_id: str, label_id: str) -> None:
        """Detach a label from a message."""
        self._require_label(label_id)
        message = self._require(message_id)
        self._replace(message.model_copy(update={"label_ids": _without(message.label_ids, label_id)}))

    def _require(self, message_id: str) -> wire.Message:
        """Return a message, or report that it does not exist."""
        message = self._messages.get(message_id)
        if message is None:
            raise NotFoundError("message", message_id)
        return message

    def _require_label(self, label_id: str) -> wire.Label:
        """Return a label, or refuse one the mailbox does not define."""
        for label in self._labels:
            if label.label_id == label_id:
                return label
        raise NotFoundError("label", label_id)

    def _label_named(self, name: str) -> wire.Label | None:
        """Return the label carrying a name, if the mailbox has one.

        The comparison ignores case, because a mailbox owner reading "Invoices"
        and "invoices" sees one label, and creating the second would be a
        surprise rather than a service.
        """
        folded = name.casefold()
        return next((label for label in self._labels if label.name.casefold() == folded), None)

    def _mint(self, name: str) -> str:
        """Return an identifier no label in this mailbox already uses.

        Two different names can slugify to the same identifier - "Project Alpha"
        and "Project/Alpha" - so the derived value is only a starting point.
        """
        taken = {label.label_id for label in self._labels}
        candidate = _label_id(name)
        if candidate not in taken:
            return candidate
        suffix = 2
        while f"{candidate}_{suffix}" in taken:
            suffix += 1
        return f"{candidate}_{suffix}"

    def _replace(self, message: wire.Message) -> None:
        """Store a modified message in place of the previous one."""
        self._messages[message.message_id] = message


class MailboxDataset:
    """The mailboxes a JSON dataset describes, addressed by owner."""

    def __init__(self, mailboxes: dict[str, InMemoryMailbox]) -> None:
        self._mailboxes = mailboxes

    def resolve(self, owner: str) -> InMemoryMailbox:
        """Return the mailbox of an owner, never another one's."""
        mailbox = self._mailboxes.get(owner)
        if mailbox is None:
            raise AccessDeniedError(f"mailbox of {owner!r} is not served here")
        return mailbox


class MailboxDatasetLoader:
    """Reads a JSON dataset into mailboxes.

    Validation failures are reported as protocol failures rather than as pydantic
    errors, because a malformed dataset is a defect in the server's own data.
    """

    def load(self, path: Path) -> MailboxDataset:
        """Load every mailbox a dataset file describes."""
        if not path.is_file():
            raise ProtocolError(f"mail dataset {str(path)!r} does not exist")
        return self.parse(self._read(path))

    def parse(self, document: dict[str, Any]) -> MailboxDataset:
        """Build the mailboxes an already-decoded dataset describes."""
        entries = document.get("mailboxes")
        if not isinstance(entries, list):
            raise ProtocolError("mail dataset has no 'mailboxes' list")
        return MailboxDataset(dict(self._mailbox(entry) for entry in entries))

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        """Decode the dataset file."""
        try:
            document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ProtocolError(f"mail dataset {str(path)!r} could not be read") from error
        return document

    @staticmethod
    def _mailbox(entry: object) -> tuple[str, InMemoryMailbox]:
        """Build one mailbox out of its dataset entry."""
        if not isinstance(entry, dict):
            raise ProtocolError("a mailbox entry is not an object")
        owner = entry.get("owner_id")
        if not isinstance(owner, str) or not owner:
            raise ProtocolError("a mailbox entry has no 'owner_id'")
        try:
            messages = [wire.Message.model_validate(item) for item in entry.get("messages") or ()]
            labels = [wire.Label.model_validate(item) for item in entry.get("labels") or ()]
        except ValidationError as error:
            raise ProtocolError(f"mailbox {owner!r} contains an invalid message or label") from error
        return owner, InMemoryMailbox(messages, labels)


class _Query:
    """Decides whether a message satisfies a search."""

    def __init__(
        self,
        *,
        keywords: str | None,
        sender: str | None,
        recipient: str | None,
        subject_contains: str | None,
        label_ids: tuple[str, ...],
        date_from: datetime | None,
        date_to: datetime | None,
        unread_only: bool,
        has_attachments: bool | None,
    ) -> None:
        self._keywords = keywords
        self._sender = sender
        self._recipient = recipient
        self._subject_contains = subject_contains
        self._label_ids = label_ids
        self._date_from = date_from
        self._date_to = date_to
        self._unread_only = unread_only
        self._has_attachments = has_attachments

    def matches(self, message: wire.Message) -> bool:
        """Whether the message satisfies every active criterion."""
        return self._matches_envelope(message) and self._matches_metadata(message)

    def _matches_envelope(self, message: wire.Message) -> bool:
        """Check the criteria bearing on who wrote what."""
        if self._sender is not None and message.sender.address != self._sender:
            return False
        if self._recipient is not None and not any(
            participant.address == self._recipient for participant in (*message.to, *message.cc)
        ):
            return False
        if self._subject_contains and self._subject_contains.casefold() not in message.subject.casefold():
            return False
        return not (self._keywords and not _contains_keywords(message, self._keywords))

    def _matches_metadata(self, message: wire.Message) -> bool:
        """Check the criteria bearing on the state and the date of a message."""
        if self._unread_only and message.is_read:
            return False
        if not all(label_id in message.label_ids for label_id in self._label_ids):
            return False
        if self._date_from is not None and message.sent_at < self._date_from:
            return False
        if self._date_to is not None and message.sent_at > self._date_to:
            return False
        return not (self._has_attachments is not None and bool(message.attachments) is not self._has_attachments)


def _contains_keywords(message: wire.Message, keywords: str) -> bool:
    """Whether every keyword appears in the subject or the body."""
    haystack = f"{message.subject} {message.body}".casefold()
    return all(keyword in haystack for keyword in keywords.casefold().split())


def _without(label_ids: tuple[str, ...], removed: str) -> tuple[str, ...]:
    """Return the label identifiers with one of them taken out."""
    return tuple(label_id for label_id in label_ids if label_id != removed)


def _label_id(name: str) -> str:
    """Mint an identifier for a new label.

    Real mail systems mint opaque ones, and a caller must never assume the
    identifier can be read back as a name. It is derived deterministically here
    all the same: this server exists to be reproducible, and a random
    identifier would make two runs of the same test differ.
    """
    slug = "".join(character if character.isalnum() else "_" for character in name).strip("_").upper()
    return f"LBL_{slug}" if slug else "LBL_UNNAMED"


def _header_of(message: wire.Message) -> wire.Header:
    """Project a message onto a search hit, without its body."""
    return wire.Header(
        message_id=message.message_id,
        thread_id=message.thread_id,
        subject=message.subject,
        sender=message.sender,
        recipient_count=len(message.to) + len(message.cc),
        sent_at=message.sent_at,
        is_read=message.is_read,
        is_archived=message.is_archived,
        has_attachments=bool(message.attachments),
        importance=message.importance,
        label_ids=message.label_ids,
    )
