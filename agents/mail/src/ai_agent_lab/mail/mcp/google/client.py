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

import logging
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
    MailLabelOutcome,
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
    GmailLabel,
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
    "create_label",
    "update_message_labels",
)

_METADATA_VIEW = "THREAD_VIEW_METADATA_ONLY"
_PLAIN_TEXT = "PLAIN_TEXT"
_logger = logging.getLogger(__name__)


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
        _logger.info("Initializing Gmail MCP tools")
        _logger.debug(
            "GmailMailTools.__init__ arguments: server=%s, transport=%s, owner_id=%s, "
            "connection_type=%s, query_builder_type=%s",
            binding.server,
            binding.transport.value,
            owner_id,
            type(connection).__name__,
            None if query_builder is None else type(query_builder).__name__,
        )
        binding.require_aliases(REQUIRED_ALIASES)
        self._connection = connection
        self._binding = binding
        self._owner_id = owner_id
        self._queries = query_builder or GmailQueryBuilder()

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query.

        This server filters through the query string alone, and its ``label:``
        operator matches names. The identifiers the request carries are
        therefore resolved to names first.
        """
        _logger.info("Calling Gmail MCP search")
        _logger.debug(
            "GmailMailTools.search arguments: request_type=%s, limit=%d, unread_only=%s, label_count=%d, user_id=%s",
            type(request).__name__,
            request.limit,
            request.unread_only,
            len(request.label_ids),
            user.user_id,
        )
        payload = await self._call(
            "search_threads",
            user,
            GmailThreadList,
            query=self._queries.build(request, await self._label_names(request, user)),
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

    async def _label_names(self, request: MailSearchRequest, user: UserContext) -> dict[str, str]:
        """Return the name of each label the request filters on."""
        _logger.info("Resolving Gmail MCP search label names")
        _logger.debug(
            "GmailMailTools._label_names arguments: label_ids=%s, user_id=%s",
            request.label_ids,
            user.user_id,
        )
        if not request.label_ids:
            return {}
        labels = await self.list_labels(user)
        _logger.info("Matching Gmail MCP search label loop")
        return {label.label_id: label.name.expose() for label in labels if label.label_id in request.label_ids}

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        _logger.debug(
            "GmailMailTools.get_message arguments: message_id=%s, user_id=%s",
            message_id,
            user.user_id,
        )
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
        _logger.info("Calling Gmail MCP thread retrieval")
        _logger.debug(
            "GmailMailTools.get_thread arguments: thread_id=%s, user_id=%s",
            thread_id,
            user.user_id,
        )
        payload = await self._call(
            "get_thread",
            user,
            GmailThread,
            threadId=thread_id,
            messageFormat=_PLAIN_TEXT,
        )
        if not payload.messages:
            raise MailToolProtocolError(f"thread {thread_id!r} was returned without a message")
        _logger.info("Mapping Gmail MCP thread message loop")
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
        _logger.info("Calling Gmail MCP label listing")
        _logger.debug("GmailMailTools.list_labels arguments: user_id=%s", user.user_id)
        payload = await self._call("list_labels", user, GmailLabelList)
        _logger.info("Mapping Gmail MCP label loop")
        return tuple(label.to_domain() for label in payload.labels)

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        _logger.info("Calling Gmail MCP draft creation")
        _logger.debug(
            "GmailMailTools.create_draft arguments: user_id=%s, to_count=%d, "
            "cc_count=%d, subject_length=%d, body_length=%d, in_reply_to=%s",
            user.user_id,
            len(draft.to),
            len(draft.cc),
            len(draft.subject.expose()),
            len(draft.body.expose()),
            draft.in_reply_to_message_id,
        )
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
        _logger.info("Rejecting unavailable Gmail MCP send")
        _logger.debug(
            "GmailMailTools.send arguments: user_id=%s, to_count=%d, cc_count=%d, subject_length=%d, body_length=%d",
            user.user_id,
            len(request.draft.to),
            len(request.draft.cc),
            len(request.draft.subject.expose()),
            len(request.draft.body.expose()),
        )
        del request, user
        raise MailToolUnavailableError(
            "the official Gmail MCP server has no send tool. Prepare a draft and send it from Gmail."
        )

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread, which Gmail expresses as a label."""
        _logger.info("Calling Gmail MCP read-state update")
        _logger.debug(
            "GmailMailTools.set_read_state arguments: message_id=%s, is_read=%s, user_id=%s",
            message_id,
            is_read,
            user.user_id,
        )
        await self._update_labels(
            message_id,
            user,
            remove=(UNREAD_LABEL,) if is_read else (),
            add=() if is_read else (UNREAD_LABEL,),
        )

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        _logger.info("Calling Gmail MCP archive")
        _logger.debug(
            "GmailMailTools.archive arguments: message_id=%s, user_id=%s",
            message_id,
            user.user_id,
        )
        await self._update_labels(message_id, user, remove=(INBOX_LABEL,))

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label to a message."""
        _logger.info("Calling Gmail MCP label application")
        _logger.debug(
            "GmailMailTools.apply_label arguments: message_id=%s, label_id=%s, user_id=%s",
            message_id,
            label_id,
            user.user_id,
        )
        await self._update_labels(message_id, user, add=(label_id,))

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label from a message."""
        _logger.info("Calling Gmail MCP label removal")
        _logger.debug(
            "GmailMailTools.remove_label arguments: message_id=%s, label_id=%s, user_id=%s",
            message_id,
            label_id,
            user.user_id,
        )
        await self._update_labels(message_id, user, remove=(label_id,))

    async def create_label(self, name: str, user: UserContext) -> MailLabelOutcome:
        """Make a label exist, reporting whether it had to be created.

        The server refuses a duplicate name, so the mailbox is read first. That
        also gives back the identifier of the existing label, which is what a
        caller wanting to file a message actually needs.
        """
        _logger.info("Calling Gmail MCP label creation")
        _logger.debug(
            "GmailMailTools.create_label arguments: name_length=%d, user_id=%s",
            len(name),
            user.user_id,
        )
        existing = await self._label_named(name, user)
        if existing is not None:
            return MailLabelOutcome(label=existing, created=False)
        payload = await self._call("create_label", user, GmailLabel, displayName=name)
        return MailLabelOutcome(label=payload.to_domain(), created=True)

    async def delete_label(self, label_id: str, user: UserContext) -> None:
        """Refuse to delete: the official Gmail server exposes no delete tool.

        Unreachable in practice, because the binding does not declare the
        capability and the agent therefore never offers it. It exists so the
        type holds, and so a misconfigured binding fails with an explanation
        rather than an attribute error.
        """
        _logger.info("Rejecting unavailable Gmail MCP label deletion")
        _logger.debug(
            "GmailMailTools.delete_label arguments: label_id=%s, user_id=%s",
            label_id,
            user.user_id,
        )
        del label_id, user
        raise MailToolUnavailableError(
            "the official Gmail MCP server has no label deletion tool. Delete the label from Gmail."
        )

    async def _label_named(self, name: str, user: UserContext) -> MailLabel | None:
        """Return the label carrying a name, if the mailbox has one."""
        _logger.info("Searching Gmail label loop by name")
        _logger.debug(
            "GmailMailTools._label_named arguments: name_length=%d, user_id=%s",
            len(name),
            user.user_id,
        )
        folded = name.casefold()
        labels = await self.list_labels(user)
        return next((label for label in labels if label.name.expose().casefold() == folded), None)

    async def _update_labels(
        self,
        message_id: str,
        user: UserContext,
        *,
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> None:
        """Apply one atomic label change."""
        _logger.info("Calling Gmail MCP atomic label update")
        _logger.debug(
            "GmailMailTools._update_labels arguments: message_id=%s, user_id=%s, add=%s, remove=%s",
            message_id,
            user.user_id,
            tuple(add),
            tuple(remove),
        )
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
        _logger.info("Flattening Gmail MCP search result loop")
        _logger.debug(
            "GmailMailTools._headers_of arguments: threads_type=%s, limit=%d, sort_order=%s",
            type(threads).__name__,
            request.limit,
            request.sort_order.value,
        )
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
        _logger.debug(
            "GmailMailTools._matches arguments: message_id=%s, unread_only=%s, "
            "sender_filter_present=%s, attachment_filter=%s, label_count=%d",
            message.message_id,
            request.unread_only,
            request.sender is not None,
            request.has_attachments,
            len(request.label_ids),
        )
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
        _logger.debug(
            "GmailMailTools._call arguments: alias=%s, user_id=%s, expected_type=%s, argument_names=%s",
            alias,
            user.user_id,
            expected.__name__,
            tuple(sorted(arguments)),
        )
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
        _logger.debug(
            "GmailMailTools._invoke arguments: alias=%s, user_id=%s, argument_names=%s",
            alias,
            user.user_id,
            tuple(sorted(arguments)),
        )
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
        _logger.debug(
            "GmailMailTools._require_owner arguments: user_id=%s, owner_match=%s",
            user.user_id,
            user.user_id == self._owner_id,
        )
        if user.user_id == self._owner_id:
            return
        raise MailAccessDeniedError(f"mailbox of {user.user_id}")

    @staticmethod
    def _text_of(result: CallToolResult) -> str:
        """Return the text a failing tool reported."""
        _logger.debug(
            "GmailMailTools._text_of arguments: content_items=%d",
            len(result.content),
        )
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
