"""The mail contract, served by the Gmail REST API.

This is what our own mail MCP server runs on. It covers the whole contract,
sending included, which the official Gmail MCP server does not offer.

The query syntax is shared with the official-server dialect: a mailbox query is
the same regardless of which door we knock on.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Sequence
from email.message import EmailMessage
from typing import Any

from ai_agent_lab.domain.mail.enums import MailSortOrder
from ai_agent_lab.domain.mail.models import (
    MailDraft,
    MailLabel,
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailSendRequest,
    MailSendResult,
    MailThread,
)
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.infrastructure.gmail.api import GmailApiClient
from ai_agent_lab.infrastructure.gmail.messages import (
    INBOX_LABEL,
    UNREAD_LABEL,
    GmailLabelReader,
    GmailMessageReader,
)
from ai_agent_lab.infrastructure.mcp.gmail.query import GmailQueryBuilder
from ai_agent_lab.mcp.mail.errors import MailNotFoundError, MailToolProtocolError

_METADATA_HEADERS = ("Subject", "From", "To", "Cc", "Date")

# Enough to keep a page of results fast, low enough to stay a polite caller.
_CONCURRENT_READS = 8


class GmailApiMailTools:
    """Mail contract implemented against the Gmail REST API."""

    def __init__(
        self,
        client: GmailApiClient,
        *,
        query_builder: GmailQueryBuilder | None = None,
        messages: GmailMessageReader | None = None,
        labels: GmailLabelReader | None = None,
    ) -> None:
        self._client = client
        self._queries = query_builder or GmailQueryBuilder()
        self._messages = messages or GmailMessageReader()
        self._labels = labels or GmailLabelReader()

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query.

        Gmail answers a query with identifiers only, so each hit needs its own
        request. They are issued concurrently and bounded: sequentially, a
        default page of twenty would take longer than a caller is willing to
        wait, and unbounded, it would hammer the API.
        """
        del user
        listing = await self._client.get(
            "/messages",
            q=self._queries.build(request) or None,
            maxResults=request.limit,
        )
        identifiers = [str(item["id"]) for item in listing.get("messages") or ()]
        messages = await self._metadata_of(identifiers)
        headers = [message.to_header() for message in messages]
        headers.sort(
            key=lambda header: header.sent_at,
            reverse=request.sort_order is MailSortOrder.NEWEST_FIRST,
        )
        estimate = int(listing.get("resultSizeEstimate", len(headers)))
        return MailSearchResult(
            headers=tuple(headers),
            total_count=max(estimate, len(headers)),
            truncated=bool(listing.get("nextPageToken")),
        )

    async def _metadata_of(self, identifiers: Sequence[str]) -> tuple[MailMessage, ...]:
        """Read the headers of several messages at once."""
        limit = asyncio.Semaphore(_CONCURRENT_READS)

        async def read(identifier: str) -> MailMessage:
            async with limit:
                return await self._metadata(identifier)

        return tuple(await asyncio.gather(*(read(identifier) for identifier in identifiers)))

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        del user
        resource = await self._client.get(f"/messages/{message_id}", format="full")
        return self._messages.to_domain(resource)

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation, oldest message first."""
        del user
        resource = await self._client.get(f"/threads/{thread_id}", format="full")
        messages = tuple(self._messages.to_domain(item) for item in resource.get("messages") or ())
        if not messages:
            raise MailNotFoundError("thread", thread_id)
        ordered = tuple(sorted(messages, key=lambda message: message.sent_at))
        return MailThread(thread_id=thread_id, subject=ordered[0].subject, messages=ordered)

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        del user
        listing = await self._client.get("/labels")
        return tuple(self._labels.to_domain(item) for item in listing.get("labels") or ())

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        del user
        created = await self._client.post("/drafts", {"message": self._encoded(draft)})
        return draft.model_copy(
            update={
                "draft_id": str(created.get("id", "")) or draft.draft_id,
                "thread_id": str((created.get("message") or {}).get("threadId", "")) or draft.thread_id,
            }
        )

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Deliver a draft to its recipients."""
        del user
        sent = await self._client.post("/messages/send", self._encoded(request.draft))
        message_id = str(sent.get("id", ""))
        if not message_id:
            raise MailToolProtocolError("Gmail accepted the message but returned no identifier")
        delivered = await self._client.get(f"/messages/{message_id}", format="metadata")
        return MailSendResult(
            message_id=message_id,
            thread_id=str(sent.get("threadId", "")) or None,
            sent_at=self._messages.to_domain(delivered).sent_at,
        )

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread, which Gmail expresses as a label."""
        del user
        await self._modify(
            message_id,
            remove=[UNREAD_LABEL] if is_read else [],
            add=[] if is_read else [UNREAD_LABEL],
        )

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        del user
        await self._modify(message_id, remove=[INBOX_LABEL])

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label to a message."""
        await self._require_label(label_id, user)
        await self._modify(message_id, add=[label_id])

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label from a message."""
        await self._require_label(label_id, user)
        await self._modify(message_id, remove=[label_id])

    async def _require_label(self, label_id: str, user: UserContext) -> None:
        """Refuse a label the mailbox does not define.

        Gmail accepts an unknown label identifier silently, which would report
        success for an operation that changed nothing.
        """
        if any(label.label_id == label_id for label in await self.list_labels(user)):
            return
        raise MailNotFoundError("label", label_id)

    async def _modify(self, message_id: str, *, add: list[str] | None = None, remove: list[str] | None = None) -> None:
        """Apply one atomic label change."""
        await self._client.post(
            f"/messages/{message_id}/modify",
            {"addLabelIds": add or [], "removeLabelIds": remove or []},
        )

    async def _metadata(self, message_id: str) -> MailMessage:
        """Read the headers of one message, without its body."""
        resource = await self._client.get(
            f"/messages/{message_id}",
            format="metadata",
            metadataHeaders=list(_METADATA_HEADERS),
        )
        return self._messages.to_domain(resource)

    @staticmethod
    def _encoded(draft: MailDraft) -> dict[str, Any]:
        """Render a draft as the RFC 2822 message Gmail expects."""
        message = EmailMessage()
        message["To"] = ", ".join(address.value for address in draft.to)
        if draft.cc:
            message["Cc"] = ", ".join(address.value for address in draft.cc)
        message["Subject"] = draft.subject.expose()
        message.set_content(draft.body.expose())
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        payload: dict[str, Any] = {"raw": raw}
        if draft.thread_id:
            payload["threadId"] = draft.thread_id
        return payload
