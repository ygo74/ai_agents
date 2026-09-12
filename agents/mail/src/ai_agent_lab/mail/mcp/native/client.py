"""Mail MCP client for a server speaking the mail protocol.

This dialect talks to a server that answers the tool names of
:mod:`mail_mcp.protocol` with the protocol payloads: the reference server, our
Gmail server, and any server built to match them, such as one on EWS or
Microsoft Graph. A server with its own shapes - the official Gmail one - gets its
own dialect rather than a flag inside this one.

Everything the server returns is validated before it becomes a domain object, and
:class:`MailWireMapper` fences every piece of free text as untrusted content on
the way in.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from mcp.types import CallToolResult, TextContent
from ygo74.agent_runtime.domains.security.user_context import UserContext

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
from ai_agent_lab.mail.mail_errors import (
    MailAccessDeniedError,
    MailToolProtocolError,
    MailToolUnavailableError,
    decode_failure,
)
from ai_agent_lab.mail.mcp.binding import McpServerBinding
from ai_agent_lab.mail.mcp.connection import McpConnection
from ai_agent_lab.mail.mcp.native.mapping import MailWireMapper
from mail_mcp.protocol import payloads as wire
from mail_mcp.protocol.tools import MailToolName

REQUIRED_ALIASES = tuple(name.value for name in MailToolName)

_OWNER = "owner"
_logger = logging.getLogger(__name__)


class McpMailTools:
    """Mail tools served by a server speaking the mail protocol."""

    def __init__(
        self,
        connection: McpConnection,
        binding: McpServerBinding,
        *,
        owner_id: str,
        mapper: MailWireMapper | None = None,
    ) -> None:
        _logger.info("Initializing native Mail MCP tools")
        _logger.debug(
            "McpMailTools.__init__ arguments: server=%s, transport=%s, owner_id=%s, connection_type=%s, mapper_type=%s",
            binding.server,
            binding.transport.value,
            owner_id,
            type(connection).__name__,
            None if mapper is None else type(mapper).__name__,
        )
        binding.require_aliases(REQUIRED_ALIASES)
        self._connection = connection
        self._binding = binding
        self._owner_id = owner_id
        self._mapper = mapper or MailWireMapper()

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query."""
        _logger.info("Calling native Mail MCP search")
        _logger.debug(
            "McpMailTools.search arguments: request_type=%s, limit=%d, unread_only=%s, label_count=%d, user_id=%s",
            type(request).__name__,
            request.limit,
            request.unread_only,
            len(request.label_ids),
            user.user_id,
        )
        payload = await self._call(
            MailToolName.SEARCH_MAIL,
            user,
            keywords=request.keywords,
            sender=None if request.sender is None else request.sender.value,
            recipient=None if request.recipient is None else request.recipient.value,
            subject_contains=request.subject_contains,
            label_ids=list(request.label_ids),
            date_from=None if request.date_from is None else request.date_from.isoformat(),
            date_to=None if request.date_to is None else request.date_to.isoformat(),
            unread_only=request.unread_only,
            has_attachments=request.has_attachments,
            limit=request.limit,
            sort_order=request.sort_order.value,
            expected=wire.SearchResult,
        )
        return self._mapper.search_result(payload)

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        _logger.debug(
            "McpMailTools.get_message arguments: message_id=%s, user_id=%s",
            message_id,
            user.user_id,
        )
        payload = await self._call(MailToolName.GET_MAIL, user, message_id=message_id, expected=wire.Message)
        return self._mapper.message(payload)

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation."""
        _logger.info("Calling native Mail MCP thread retrieval")
        _logger.debug(
            "McpMailTools.get_thread arguments: thread_id=%s, user_id=%s",
            thread_id,
            user.user_id,
        )
        payload = await self._call(MailToolName.GET_THREAD, user, thread_id=thread_id, expected=wire.Thread)
        return self._mapper.thread(payload)

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        _logger.info("Calling native Mail MCP label listing")
        _logger.debug("McpMailTools.list_labels arguments: user_id=%s", user.user_id)
        payload = await self._call(MailToolName.LIST_LABELS, user, expected=wire.Labels)
        return self._mapper.labels(payload)

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        _logger.info("Calling native Mail MCP draft creation")
        _logger.debug(
            "McpMailTools.create_draft arguments: user_id=%s, to_count=%d, "
            "cc_count=%d, subject_length=%d, body_length=%d, in_reply_to=%s",
            user.user_id,
            len(draft.to),
            len(draft.cc),
            len(draft.subject.expose()),
            len(draft.body.expose()),
            draft.in_reply_to_message_id,
        )
        payload = await self._call(
            MailToolName.CREATE_DRAFT,
            user,
            draft=self._mapper.to_wire(draft).model_dump(mode="json"),
            expected=wire.Draft,
        )
        return self._mapper.draft(payload)

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Deliver a draft to its recipients."""
        _logger.info("Calling native Mail MCP send")
        _logger.debug(
            "McpMailTools.send arguments: user_id=%s, to_count=%d, cc_count=%d, "
            "subject_length=%d, body_length=%d, in_reply_to=%s",
            user.user_id,
            len(request.draft.to),
            len(request.draft.cc),
            len(request.draft.subject.expose()),
            len(request.draft.body.expose()),
            request.draft.in_reply_to_message_id,
        )
        payload = await self._call(
            MailToolName.SEND_MAIL,
            user,
            draft=self._mapper.to_wire(request.draft).model_dump(mode="json"),
            expected=wire.SendResult,
        )
        return self._mapper.send_result(payload)

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread."""
        _logger.info("Calling native Mail MCP read-state update")
        _logger.debug(
            "McpMailTools.set_read_state arguments: message_id=%s, is_read=%s, user_id=%s",
            message_id,
            is_read,
            user.user_id,
        )
        await self._acknowledge(MailToolName.MARK_READ, user, message_id=message_id, is_read=is_read)

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        _logger.info("Calling native Mail MCP archive")
        _logger.debug(
            "McpMailTools.archive arguments: message_id=%s, user_id=%s",
            message_id,
            user.user_id,
        )
        await self._acknowledge(MailToolName.ARCHIVE_MAIL, user, message_id=message_id)

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label to a message."""
        _logger.info("Calling native Mail MCP label application")
        _logger.debug(
            "McpMailTools.apply_label arguments: message_id=%s, label_id=%s, user_id=%s",
            message_id,
            label_id,
            user.user_id,
        )
        await self._acknowledge(MailToolName.APPLY_LABEL, user, message_id=message_id, label_id=label_id)

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label from a message."""
        _logger.info("Calling native Mail MCP label removal")
        _logger.debug(
            "McpMailTools.remove_label arguments: message_id=%s, label_id=%s, user_id=%s",
            message_id,
            label_id,
            user.user_id,
        )
        await self._acknowledge(MailToolName.REMOVE_LABEL, user, message_id=message_id, label_id=label_id)

    async def create_label(self, name: str, user: UserContext) -> MailLabelOutcome:
        """Make a label exist, reporting whether it had to be created."""
        _logger.info("Calling native Mail MCP label creation")
        _logger.debug(
            "McpMailTools.create_label arguments: name_length=%d, user_id=%s",
            len(name),
            user.user_id,
        )
        payload = await self._call(MailToolName.CREATE_LABEL, user, name=name, expected=wire.CreatedLabel)
        return self._mapper.label_outcome(payload)

    async def delete_label(self, label_id: str, user: UserContext) -> None:
        """Delete a label, detaching it from every message carrying it."""
        _logger.info("Calling native Mail MCP label deletion")
        _logger.debug(
            "McpMailTools.delete_label arguments: label_id=%s, user_id=%s",
            label_id,
            user.user_id,
        )
        await self._acknowledge(MailToolName.DELETE_LABEL, user, label_id=label_id)

    async def _call[PayloadT: wire.Payload](
        self,
        tool: MailToolName,
        user: UserContext,
        *,
        expected: type[PayloadT],
        **arguments: Any,
    ) -> PayloadT:
        """Invoke a tool and validate the payload it returned."""
        _logger.debug(
            "McpMailTools._call arguments: tool_name=%s, user_id=%s, expected_type=%s, argument_names=%s",
            tool.value,
            user.user_id,
            expected.__name__,
            tuple(sorted(arguments)),
        )
        result = await self._invoke(tool, user, arguments)
        return self._validated(result, expected, tool)

    async def _acknowledge(self, tool: MailToolName, user: UserContext, **arguments: Any) -> None:
        """Invoke a tool whose success carries no payload."""
        _logger.debug(
            "McpMailTools._acknowledge arguments: tool_name=%s, user_id=%s, argument_names=%s",
            tool.value,
            user.user_id,
            tuple(sorted(arguments)),
        )
        await self._invoke(tool, user, arguments)

    async def _invoke(self, tool: MailToolName, user: UserContext, arguments: Mapping[str, Any]) -> CallToolResult:
        """Send one tool call, refusing another mailbox and decoding failures."""
        _logger.debug(
            "McpMailTools._invoke arguments: tool_name=%s, user_id=%s, argument_names=%s",
            tool.value,
            user.user_id,
            tuple(sorted(arguments)),
        )
        self._require_owner(user)
        session = await self._connection.session()
        payload = {key: value for key, value in arguments.items() if value is not None}
        try:
            result = await session.call_tool(self._binding.remote(tool.value), {_OWNER: user.user_id, **payload})
        except Exception as error:
            raise MailToolUnavailableError(
                f"mail tool {tool.value!r} could not be called: {type(error).__name__}"
            ) from error
        if result.isError:
            raise decode_failure(self._text_of(result))
        return result

    def _require_owner(self, user: UserContext) -> None:
        """Never ask a server for a mailbox other than the one it serves.

        The server remains the authority on authorisation. Not even asking is
        the cheaper half of that rule, and it holds whatever the server does.
        """
        _logger.debug(
            "McpMailTools._require_owner arguments: user_id=%s, owner_match=%s",
            user.user_id,
            user.user_id == self._owner_id,
        )
        if user.user_id == self._owner_id:
            return
        raise MailAccessDeniedError(f"mailbox of {user.user_id}")

    @staticmethod
    def _validated[PayloadT: wire.Payload](
        result: CallToolResult,
        expected: type[PayloadT],
        tool: MailToolName,
    ) -> PayloadT:
        """Turn the structured answer of a tool into a validated payload."""
        _logger.debug(
            "McpMailTools._validated arguments: tool_name=%s, expected_type=%s, structured_content_present=%s",
            tool.value,
            expected.__name__,
            result.structuredContent is not None,
        )
        structured = result.structuredContent
        if structured is None:
            raise MailToolProtocolError(f"mail tool {tool.value!r} returned no structured content")
        try:
            return expected.model_validate(structured)
        except ValueError as error:
            raise MailToolProtocolError(f"mail tool {tool.value!r} returned an unusable {expected.__name__}") from error

    @staticmethod
    def _text_of(result: CallToolResult) -> str:
        """Return the text a failing tool reported."""
        _logger.debug(
            "McpMailTools._text_of arguments: content_items=%d",
            len(result.content),
        )
        return " ".join(item.text for item in result.content if isinstance(item, TextContent)).strip()
