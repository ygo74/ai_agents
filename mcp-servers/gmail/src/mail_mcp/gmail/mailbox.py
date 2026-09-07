"""The mailbox this server serves, backed by the Gmail REST API.

Everything here speaks the protocol on one side and Gmail on the other. It knows
nothing of agents, skills or domain models: a caller decides what a message
means.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Sequence
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from mail_mcp.gmail.api import GmailApiClient, GmailConflictError
from mail_mcp.gmail.messages import (
    INBOX_LABEL,
    UNREAD_LABEL,
    GmailLabelReader,
    GmailMessageReader,
)
from mail_mcp.gmail.query import GmailQuery
from mail_mcp.protocol import payloads as wire
from mail_mcp.protocol.errors import NotFoundError, ProtocolError
from mail_mcp.protocol.rules import require_deletable

_METADATA_HEADERS = ("Subject", "From", "To", "Cc", "Date")

# Enough to keep a page of results fast, low enough to stay a polite caller.
_CONCURRENT_READS = 8


class GmailMailbox:
    """Serves the mail protocol from a real Gmail mailbox."""

    def __init__(
        self,
        client: GmailApiClient,
        *,
        query: GmailQuery | None = None,
        messages: GmailMessageReader | None = None,
        labels: GmailLabelReader | None = None,
    ) -> None:
        self._client = client
        self._query = query or GmailQuery()
        self._messages = messages or GmailMessageReader()
        self._labels = labels or GmailLabelReader()

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
        """Return the message headers matching a query.

        Gmail answers a query with identifiers only, so each hit needs its own
        request. They are issued concurrently and bounded: sequentially, a page
        of twenty would take longer than a caller is willing to wait.

        Labels travel as ``labelIds`` rather than inside the query, because the
        ``label:`` operator matches a name and a caller holds an identifier.
        Gmail narrows on each one, so several labels mean messages carrying all
        of them.
        """
        listing = await self._client.get(
            "/messages",
            q=self._query.build(
                keywords=keywords,
                sender=sender,
                recipient=recipient,
                subject_contains=subject_contains,
                date_from=date_from,
                date_to=date_to,
                unread_only=unread_only,
                has_attachments=has_attachments,
            )
            or None,
            labelIds=list(label_ids) or None,
            maxResults=limit,
        )
        identifiers = [str(item["id"]) for item in listing.get("messages") or ()]
        headers = list(await self._headers_of(identifiers))
        headers.sort(
            key=lambda header: header.sent_at,
            reverse=sort_order is wire.SortOrder.NEWEST_FIRST,
        )
        estimate = int(listing.get("resultSizeEstimate", len(headers)))
        return wire.SearchResult(
            headers=tuple(headers),
            total_count=max(estimate, len(headers)),
            truncated=bool(listing.get("nextPageToken")),
        )

    async def get_message(self, message_id: str) -> wire.Message:
        """Return one complete message."""
        return self._messages.to_wire(await self._client.get(f"/messages/{message_id}", format="full"))

    async def get_thread(self, thread_id: str) -> wire.Thread:
        """Return a full conversation, oldest message first."""
        resource = await self._client.get(f"/threads/{thread_id}", format="full")
        messages = tuple(self._messages.to_wire(item) for item in resource.get("messages") or ())
        if not messages:
            raise NotFoundError("thread", thread_id)
        ordered = tuple(sorted(messages, key=lambda message: message.sent_at))
        return wire.Thread(thread_id=thread_id, subject=ordered[0].subject, messages=ordered)

    async def list_labels(self) -> wire.Labels:
        """Return the labels available in the mailbox."""
        listing = await self._client.get("/labels")
        return wire.Labels(labels=tuple(self._labels.to_wire(item) for item in listing.get("labels") or ()))

    async def create_label(self, name: str) -> wire.CreatedLabel:
        """Make a label exist, returning whether it had to be created.

        Gmail refuses a duplicate name outright, so the mailbox is read first.
        The refusal is still handled: a label created between the read and the
        write is a race, not a failure the caller should see.
        """
        existing = await self._label_named(name)
        if existing is not None:
            return wire.CreatedLabel(label=existing, created=False)
        try:
            created = await self._client.post("/labels", {"name": name})
        except GmailConflictError:
            return await self._existing(name)
        return wire.CreatedLabel(label=self._labels.to_wire(created), created=True)

    async def delete_label(self, label_id: str) -> None:
        """Delete a label. Gmail detaches it from every message carrying it."""
        require_deletable(await self._require_label(label_id))
        await self._client.delete(f"/labels/{label_id}")

    async def create_draft(self, draft: wire.Draft) -> wire.Draft:
        """Persist a draft without delivering anything."""
        created = await self._client.post("/drafts", {"message": self._encoded(draft)})
        return draft.model_copy(
            update={
                "draft_id": str(created.get("id", "")) or draft.draft_id,
                "thread_id": str((created.get("message") or {}).get("threadId", "")) or draft.thread_id,
            }
        )

    async def send(self, draft: wire.Draft) -> wire.SendResult:
        """Deliver a draft to its recipients."""
        sent = await self._client.post("/messages/send", self._encoded(draft))
        message_id = str(sent.get("id", ""))
        if not message_id:
            raise ProtocolError("Gmail accepted the message but returned no identifier")
        delivered = await self._client.get(f"/messages/{message_id}", format="metadata")
        return wire.SendResult(
            message_id=message_id,
            thread_id=str(sent.get("threadId", "")) or None,
            sent_at=self._messages.to_wire(delivered).sent_at,
        )

    async def set_read_state(self, message_id: str, is_read: bool) -> None:
        """Mark a message as read or unread, which Gmail expresses as a label."""
        await self._modify(
            message_id,
            remove=[UNREAD_LABEL] if is_read else [],
            add=[] if is_read else [UNREAD_LABEL],
        )

    async def archive(self, message_id: str) -> None:
        """Remove a message from the inbox without deleting it."""
        await self._modify(message_id, remove=[INBOX_LABEL])

    async def apply_label(self, message_id: str, label_id: str) -> None:
        """Attach a label to a message."""
        await self._require_label(label_id)
        await self._modify(message_id, add=[label_id])

    async def remove_label(self, message_id: str, label_id: str) -> None:
        """Detach a label from a message."""
        await self._require_label(label_id)
        await self._modify(message_id, remove=[label_id])

    async def aclose(self) -> None:
        """Release the HTTP connection pool."""
        await self._client.aclose()

    async def _require_label(self, label_id: str) -> wire.Label:
        """Return a label, or refuse one the mailbox does not define.

        Gmail accepts an unknown label identifier silently, which would report
        success for an operation that changed nothing.
        """
        labels = await self.list_labels()
        found = next((label for label in labels.labels if label.label_id == label_id), None)
        if found is None:
            raise NotFoundError("label", label_id)
        return found

    async def _label_named(self, name: str) -> wire.Label | None:
        """Return the label carrying a name, if the mailbox has one.

        The comparison ignores case, because a mailbox owner reading "Invoices"
        and "invoices" sees one label, and Gmail refuses the second anyway.
        """
        folded = name.casefold()
        labels = await self.list_labels()
        return next((label for label in labels.labels if label.name.casefold() == folded), None)

    async def _existing(self, name: str) -> wire.CreatedLabel:
        """Return the label Gmail says already exists."""
        found = await self._label_named(name)
        if found is None:
            raise ProtocolError(f"Gmail reports label {name!r} exists but does not list it")
        return wire.CreatedLabel(label=found, created=False)

    async def _modify(self, message_id: str, *, add: list[str] | None = None, remove: list[str] | None = None) -> None:
        """Apply one atomic label change."""
        await self._client.post(
            f"/messages/{message_id}/modify",
            {"addLabelIds": add or [], "removeLabelIds": remove or []},
        )

    async def _headers_of(self, identifiers: Sequence[str]) -> tuple[wire.Header, ...]:
        """Read the headers of several messages at once."""
        limit = asyncio.Semaphore(_CONCURRENT_READS)

        async def read(identifier: str) -> wire.Header:
            async with limit:
                resource = await self._client.get(
                    f"/messages/{identifier}",
                    format="metadata",
                    metadataHeaders=list(_METADATA_HEADERS),
                )
                return self._messages.to_header(resource)

        return tuple(await asyncio.gather(*(read(identifier) for identifier in identifiers)))

    @staticmethod
    def _encoded(draft: wire.Draft) -> dict[str, Any]:
        """Render a draft as the RFC 2822 message Gmail expects."""
        message = EmailMessage()
        message["To"] = ", ".join(draft.to)
        if draft.cc:
            message["Cc"] = ", ".join(draft.cc)
        message["Subject"] = draft.subject
        message.set_content(draft.body)
        payload: dict[str, Any] = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
        if draft.thread_id:
            payload["threadId"] = draft.thread_id
        return payload
