"""Deterministic mailbox used by the mock runtime mode and by the tests.

This is an infrastructure implementation of the mail MCP contract backed by an
in-memory dataset. It exists so the agent, the skills and the confirmation
model can be exercised end to end without Gmail, without credentials and
without a network.

It is not a shortcut around the architecture: it sits exactly where a real MCP
client sits and honours the same contract, validated by the same conformance
suite.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.mail.domain.enums import MailSortOrder
from ai_agent_lab.mail.domain.models import (
    MailDraft,
    MailLabel,
    MailLabelOutcome,
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailSendRequest,
    MailSendResult,
    MailThread,
)
from ai_agent_lab.mail.mail_errors import MailAccessDeniedError, MailNotFoundError


class Mailbox:
    """The messages, labels and drafts owned by one user."""

    def __init__(
        self,
        owner_id: str,
        messages: Iterable[MailMessage] = (),
        labels: Iterable[MailLabel] = (),
    ) -> None:
        self.owner_id = owner_id
        self._messages: dict[str, MailMessage] = {message.message_id: message for message in messages}
        self._labels: dict[str, MailLabel] = {label.label_id: label for label in labels}
        self._drafts: dict[str, MailDraft] = {}
        self._sent: list[MailSendResult] = []

    @property
    def messages(self) -> tuple[MailMessage, ...]:
        """Every message currently stored."""
        return tuple(self._messages.values())

    @property
    def labels(self) -> tuple[MailLabel, ...]:
        """Every label currently stored."""
        return tuple(self._labels.values())

    @property
    def drafts(self) -> tuple[MailDraft, ...]:
        """Every draft currently stored."""
        return tuple(self._drafts.values())

    @property
    def sent(self) -> tuple[MailSendResult, ...]:
        """Every message delivered from this mailbox."""
        return tuple(self._sent)

    def message(self, message_id: str) -> MailMessage:
        """Return a message or fail."""
        found = self._messages.get(message_id)
        if found is None:
            raise MailNotFoundError("message", message_id)
        return found

    def thread(self, thread_id: str) -> MailThread:
        """Return a conversation or fail."""
        messages = tuple(m for m in self._messages.values() if m.thread_id == thread_id)
        if not messages:
            raise MailNotFoundError("thread", thread_id)
        ordered = tuple(sorted(messages, key=lambda message: message.sent_at))
        return MailThread(thread_id=thread_id, subject=ordered[0].subject, messages=ordered)

    def replace(self, message: MailMessage) -> None:
        """Store an updated version of a message."""
        self._messages[message.message_id] = message

    def store_draft(self, draft: MailDraft) -> MailDraft:
        """Persist a draft, assigning an identifier when needed."""
        stored = draft if draft.draft_id else draft.model_copy(update={"draft_id": f"draft-{uuid.uuid4().hex[:8]}"})
        self._drafts[str(stored.draft_id)] = stored
        return stored

    def record_sent(self, result: MailSendResult) -> None:
        """Record a delivery."""
        self._sent.append(result)

    def require_label(self, label_id: str) -> MailLabel:
        """Return a label or fail."""
        found = self._labels.get(label_id)
        if found is None:
            raise MailNotFoundError("label", label_id)
        return found

    def label_named(self, name: str) -> MailLabel | None:
        """Return the label carrying a name, if this mailbox has one.

        The comparison ignores case: a mailbox owner reading "Invoices" and
        "invoices" sees one label, not two.
        """
        folded = name.casefold()
        return next((label for label in self._labels.values() if label.name.expose().casefold() == folded), None)

    def add_label(self, label: MailLabel) -> MailLabel:
        """Store a new label."""
        self._labels[label.label_id] = label
        return label

    def drop_label(self, label_id: str) -> None:
        """Delete a label and detach it from every message carrying it.

        The detachment is what a real mail system does, so a caller that tested
        against this mailbox and then met a real one finds no surprise.
        """
        del self._labels[label_id]
        for message in list(self._messages.values()):
            if label_id not in message.label_ids:
                continue
            remaining = tuple(existing for existing in message.label_ids if existing != label_id)
            self.replace(message.model_copy(update={"label_ids": remaining}))

    def mint_label_id(self, name: str) -> str:
        """Return an identifier no label in this mailbox already uses.

        Derived from the name so a run is reproducible, and disambiguated
        because two names can reduce to the same value.
        """
        slug = "".join(character if character.isalnum() else "_" for character in name).strip("_").upper()
        candidate = f"LBL_{slug}" if slug else "LBL_UNNAMED"
        if candidate not in self._labels:
            return candidate
        suffix = 2
        while f"{candidate}_{suffix}" in self._labels:
            suffix += 1
        return f"{candidate}_{suffix}"


class InMemoryMailTools:
    """Mail MCP contract served from in-memory mailboxes."""

    def __init__(self, mailboxes: Mapping[str, Mailbox], *, clock: type[datetime] = datetime) -> None:
        self._mailboxes = dict(mailboxes)
        self._clock = clock
        self._matcher = MailSearchMatcher()

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query."""
        mailbox = self._mailbox_of(user)
        matching = [message for message in mailbox.messages if self._matcher.matches(message, request)]
        matching.sort(
            key=lambda message: message.sent_at,
            reverse=request.sort_order is MailSortOrder.NEWEST_FIRST,
        )
        page = tuple(message.to_header() for message in matching[: request.limit])
        return MailSearchResult(
            headers=page,
            total_count=len(matching),
            truncated=len(matching) > len(page),
        )

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        return self._mailbox_of(user).message(message_id)

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation."""
        return self._mailbox_of(user).thread(thread_id)

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        return self._mailbox_of(user).labels

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        return self._mailbox_of(user).store_draft(draft)

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Deliver a draft to its recipients."""
        mailbox = self._mailbox_of(user)
        result = MailSendResult(
            message_id=f"sent-{uuid.uuid4().hex[:8]}",
            thread_id=request.draft.thread_id,
            sent_at=self._clock.now(UTC),
        )
        mailbox.record_sent(result)
        return result

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread."""
        mailbox = self._mailbox_of(user)
        mailbox.replace(mailbox.message(message_id).model_copy(update={"is_read": is_read}))

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        mailbox = self._mailbox_of(user)
        mailbox.replace(mailbox.message(message_id).model_copy(update={"is_archived": True}))

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label to a message."""
        mailbox = self._mailbox_of(user)
        mailbox.require_label(label_id)
        message = mailbox.message(message_id)
        if label_id in message.label_ids:
            return
        mailbox.replace(message.model_copy(update={"label_ids": (*message.label_ids, label_id)}))

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label from a message."""
        mailbox = self._mailbox_of(user)
        mailbox.require_label(label_id)
        message = mailbox.message(message_id)
        remaining = tuple(existing for existing in message.label_ids if existing != label_id)
        mailbox.replace(message.model_copy(update={"label_ids": remaining}))

    async def create_label(self, name: str, user: UserContext) -> MailLabelOutcome:
        """Make a label exist, reporting whether it had to be created."""
        mailbox = self._mailbox_of(user)
        existing = mailbox.label_named(name)
        if existing is not None:
            return MailLabelOutcome(label=existing, created=False)
        label = mailbox.add_label(
            MailLabel(
                label_id=mailbox.mint_label_id(name),
                name=untrusted(name, UntrustedOrigin.MAIL_LABEL),
                is_system=False,
            )
        )
        return MailLabelOutcome(label=label, created=True)

    async def delete_label(self, label_id: str, user: UserContext) -> None:
        """Delete a label, detaching it from every message carrying it."""
        mailbox = self._mailbox_of(user)
        label = mailbox.require_label(label_id)
        if label.is_system:
            raise MailAccessDeniedError(f"label {label.name.expose()!r} is a system label and cannot be deleted")
        mailbox.drop_label(label_id)

    def mailbox_of(self, user: UserContext) -> Mailbox:
        """Expose a mailbox for assertions in tests and demos."""
        return self._mailbox_of(user)

    def _mailbox_of(self, user: UserContext) -> Mailbox:
        """Return the caller's mailbox, never another user's."""
        mailbox = self._mailboxes.get(user.user_id)
        if mailbox is None:
            raise MailAccessDeniedError(f"mailbox of {user.user_id}")
        return mailbox


class MailSearchMatcher:
    """Decides whether a message satisfies a structured query.

    A real MCP server delegates this to the mail system; the in-memory mailbox
    has to reproduce it. The rules are split in two cohesive groups to keep each
    method short and easy to reason about.
    """

    def matches(self, message: MailMessage, request: MailSearchRequest) -> bool:
        """Whether the message satisfies every active criterion."""
        return self._matches_envelope(message, request) and self._matches_metadata(message, request)

    @staticmethod
    def _matches_envelope(message: MailMessage, request: MailSearchRequest) -> bool:
        """Check the criteria bearing on who wrote what."""
        if request.sender is not None and message.sender.address != request.sender:
            return False
        if request.recipient is not None and not any(
            participant.address == request.recipient for participant in (*message.to, *message.cc)
        ):
            return False
        if request.subject_contains and request.subject_contains.casefold() not in message.subject.expose().casefold():
            return False
        return not (request.keywords and not _contains_keywords(message, request.keywords))

    @staticmethod
    def _matches_metadata(message: MailMessage, request: MailSearchRequest) -> bool:
        """Check the criteria bearing on the state and the date of a message."""
        if request.unread_only and message.is_read:
            return False
        if not all(label_id in message.label_ids for label_id in request.label_ids):
            return False
        if request.date_from is not None and message.sent_at < request.date_from:
            return False
        if request.date_to is not None and message.sent_at > request.date_to:
            return False
        return not (request.has_attachments is not None and message.has_attachments is not request.has_attachments)


def _contains_keywords(message: MailMessage, keywords: str) -> bool:
    """Whether every keyword appears in the subject or the body."""
    haystack = f"{message.subject.expose()} {message.body.expose()}".casefold()
    return all(keyword in haystack for keyword in keywords.casefold().split())
