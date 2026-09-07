"""Mail contract served by the official Gmail MCP server.

This is the only class that knows Gmail vocabulary. It reconciles two honest
differences with our contract:

- Gmail searches **threads**, not messages. The messages of the matching
  conversations are flattened into headers, then the criteria that can be
  checked on metadata are re-applied, because a thread matches as soon as one
  of its messages does.
- Gmail has **no send tool**. Sending is therefore refused here and, more
  importantly, never offered to the model: the binding does not declare the
  capability, so no tool for it is ever built.

Reading state and archiving are labels in Gmail. ``UNREAD`` and ``INBOX`` are
written through one atomic tool, which is also what applies and removes any
other label.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from mcp.types import CallToolResult, TextContent

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.mail.domain.enums import MailSortOrder
from ai_agent_lab.mail.domain.models import (
    MailDraft,
    MailHeader,
    MailLabel,
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailSendRequest,
    MailSendResult,
    MailThread,
)
from ai_agent_lab.mail.mail_errors import (
    MailAccessDeniedError,
    MailToolProtocolError,
    MailToolUnavailableError,
    decode_failure,
)
from ai_agent_lab.mail.mcp.binding import McpServerBinding
from ai_agent_lab.mail.mcp.connection import McpConnection
from ai_agent_lab.mail.mcp.google.payloads import (
    INBOX_LABEL,
    UNREAD_LABEL,
    GmailDraft,
    GmailLabelList,
    GmailMessage,
    GmailPayload,
    GmailThread,
    GmailThreadList,
)
from ai_agent_lab.mail.mcp.google.query import GmailQueryBuilder

REQUIRED_ALIASES = (
    "search_threads",
    "get_message",
    "get_thread",
    "list_labels",
    "create_draft",
    "update_message_labels",
)

_METADATA_VIEW = "THREAD_VIEW_METADATA_ONLY"
_PLAIN_TEXT = "PLAIN_TEXT"


class GmailMailTools:
    """Mail MCP contract served by the official Gmail server."""

    def __init__(
        self,
        connection: McpConnection,
        binding: McpServerBinding,
        *,
        owner_id: str,
        query_builder: GmailQueryBuilder | None = None,
    ) -> None:
        binding.require_aliases(REQUIRED_ALIASES)
        self._connection = connection
        self._binding = binding
        self._owner_id = owner_id
        self._queries = query_builder or GmailQueryBuilder()

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query."""
        payload = await self._call(
            "search_threads",
            user,
            GmailThreadList,
            query=self._queries.build(request),
            pageSize=request.limit,
            view=_METADATA_VIEW,
        )
        headers = self._headers_of(payload.threads, request)
        page = headers[: request.limit]
        return MailSearchResult(
            headers=page,
            total_count=max(len(headers), payload.estimated_total),
            truncated=len(headers) > len(page) or bool(payload.next_page_token),
        )

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        payload = await self._call(
            "get_message",
            user,
            GmailMessage,
            messageId=message_id,
            messageFormat=_PLAIN_TEXT,
        )
        return payload.to_domain()

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation, oldest message first."""
        payload = await self._call(
            "get_thread",
            user,
            GmailThread,
            threadId=thread_id,
            messageFormat=_PLAIN_TEXT,
        )
        if not payload.messages:
            raise MailToolProtocolError(f"thread {thread_id!r} was returned without a message")
        messages = tuple(
            message.to_domain(fallback_thread_id=payload.thread_id or thread_id) for message in payload.messages
        )
        ordered = tuple(sorted(messages, key=lambda message: message.sent_at))
        return MailThread(
            thread_id=payload.thread_id or thread_id,
            subject=untrusted(payload.messages[0].subject, UntrustedOrigin.MAIL_SUBJECT),
            messages=ordered,
        )

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        payload = await self._call("list_labels", user, GmailLabelList)
        return tuple(label.to_domain() for label in payload.labels)

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        payload = await self._call(
            "create_draft",
            user,
            GmailDraft,
            to=[address.value for address in draft.to],
            cc=[address.value for address in draft.cc],
            subject=draft.subject.expose(),
            body=draft.body.expose(),
            replyToMessageId=draft.in_reply_to_message_id,
        )
        return draft.model_copy(
            update={
                "draft_id": payload.draft_id or draft.draft_id,
                "thread_id": payload.thread_id or draft.thread_id,
            }
        )

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Refuse to send: the official Gmail server exposes no send tool."""
        del request, user
        raise MailToolUnavailableError(
            "the official Gmail MCP server has no send tool. Prepare a draft and send it from Gmail."
        )

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread, which Gmail expresses as a label."""
        await self._update_labels(
            message_id,
            user,
            remove=(UNREAD_LABEL,) if is_read else (),
            add=() if is_read else (UNREAD_LABEL,),
        )

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        await self._update_labels(message_id, user, remove=(INBOX_LABEL,))

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label to a message."""
        await self._update_labels(message_id, user, add=(label_id,))

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label from a message."""
        await self._update_labels(message_id, user, remove=(label_id,))

    async def _update_labels(
        self,
        message_id: str,
        user: UserContext,
        *,
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> None:
        """Apply one atomic label change."""
        await self._invoke(
            "update_message_labels",
            user,
            {"messageId": message_id, "addLabelIds": list(add), "removeLabelIds": list(remove)},
        )

    def _headers_of(
        self,
        threads: Iterable[GmailThread],
        request: MailSearchRequest,
    ) -> tuple[MailHeader, ...]:
        """Flatten matching conversations into ordered message headers.

        Gmail returns a thread as soon as one of its messages matches, so the
        criteria that metadata can answer are re-applied. Keywords and subject
        are left to Gmail: judging them here would need the body, which a
        metadata view does not carry.
        """
        headers = [
            message.to_header(fallback_thread_id=thread.thread_id)
            for thread in threads
            for message in thread.messages
            if self._matches(message, request)
        ]
        headers.sort(
            key=lambda header: header.sent_at,
            reverse=request.sort_order is MailSortOrder.NEWEST_FIRST,
        )
        return tuple(headers)

    @staticmethod
    def _matches(message: GmailMessage, request: MailSearchRequest) -> bool:
        """Whether a message of a matching thread satisfies the metadata criteria."""
        if request.unread_only and message.is_read:
            return False
        if request.sender is not None and request.sender.value not in message.sender.casefold():
            return False
        if request.has_attachments is not None and message.has_attachments is not request.has_attachments:
            return False
        if request.label_ids and not any(label in message.label_ids for label in request.label_ids):
            return False
        return _within_dates(message, request)

    async def _call[PayloadT: GmailPayload](
        self,
        alias: str,
        user: UserContext,
        expected: type[PayloadT],
        **arguments: Any,
    ) -> PayloadT:
        """Invoke a tool and validate the payload it returned."""
        result = await self._invoke(alias, user, arguments)
        structured = result.structuredContent
        if structured is None:
            raise MailToolProtocolError(f"gmail tool {alias!r} returned no structured content")
        try:
            return expected.model_validate(structured)
        except ValueError as error:
            raise MailToolProtocolError(f"gmail tool {alias!r} returned an unusable {expected.__name__}") from error

    async def _invoke(self, alias: str, user: UserContext, arguments: dict[str, Any]) -> CallToolResult:
        """Send one tool call, refusing another mailbox and decoding failures."""
        self._require_owner(user)
        session = await self._connection.session()
        payload = {key: value for key, value in arguments.items() if value is not None}
        try:
            result = await session.call_tool(self._binding.remote(alias), payload)
        except Exception as error:
            raise MailToolUnavailableError(
                f"gmail tool {alias!r} could not be called: {type(error).__name__}"
            ) from error
        if result.isError:
            raise decode_failure(self._text_of(result))
        return result

    def _require_owner(self, user: UserContext) -> None:
        """Never ask the server for a mailbox other than the authenticated one.

        The Gmail server always acts for the account that consented, so asking
        on behalf of anybody else would silently read the wrong mailbox.
        """
        if user.user_id == self._owner_id:
            return
        raise MailAccessDeniedError(f"mailbox of {user.user_id}")

    @staticmethod
    def _text_of(result: CallToolResult) -> str:
        """Return the text a failing tool reported."""
        return " ".join(item.text for item in result.content if isinstance(item, TextContent)).strip()


def _within_dates(message: GmailMessage, request: MailSearchRequest) -> bool:
    """Whether a message falls inside the requested bounds."""
    if request.date_from is None and request.date_to is None:
        return True
    sent_at = message.date
    if sent_at is None:
        return False
    if request.date_from is not None and sent_at < request.date_from:
        return False
    return not (request.date_to is not None and sent_at > request.date_to)
