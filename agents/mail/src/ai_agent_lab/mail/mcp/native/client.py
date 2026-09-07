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

from collections.abc import Mapping
from typing import Any

from mcp.types import CallToolResult, TextContent

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.models import (
    MailDraft,
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
from ai_agent_lab.mail.mcp.native.mapping import MailWireMapper
from mail_mcp.protocol import payloads as wire
from mail_mcp.protocol.tools import MailToolName

REQUIRED_ALIASES = tuple(name.value for name in MailToolName)

_OWNER = "owner"


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
        binding.require_aliases(REQUIRED_ALIASES)
        self._connection = connection
        self._binding = binding
        self._owner_id = owner_id
        self._mapper = mapper or MailWireMapper()

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query."""
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
        payload = await self._call(MailToolName.GET_MAIL, user, message_id=message_id, expected=wire.Message)
        return self._mapper.message(payload)

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation."""
        payload = await self._call(MailToolName.GET_THREAD, user, thread_id=thread_id, expected=wire.Thread)
        return self._mapper.thread(payload)

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        payload = await self._call(MailToolName.LIST_LABELS, user, expected=wire.Labels)
        return self._mapper.labels(payload)

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        payload = await self._call(
            MailToolName.CREATE_DRAFT,
            user,
            draft=self._mapper.to_wire(draft).model_dump(mode="json"),
            expected=wire.Draft,
        )
        return self._mapper.draft(payload)

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Deliver a draft to its recipients."""
        payload = await self._call(
            MailToolName.SEND_MAIL,
            user,
            draft=self._mapper.to_wire(request.draft).model_dump(mode="json"),
            expected=wire.SendResult,
        )
        return self._mapper.send_result(payload)

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread."""
        await self._acknowledge(MailToolName.MARK_READ, user, message_id=message_id, is_read=is_read)

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        await self._acknowledge(MailToolName.ARCHIVE_MAIL, user, message_id=message_id)

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label to a message."""
        await self._acknowledge(MailToolName.APPLY_LABEL, user, message_id=message_id, label_id=label_id)

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label from a message."""
        await self._acknowledge(MailToolName.REMOVE_LABEL, user, message_id=message_id, label_id=label_id)

    async def _call[PayloadT: wire.Payload](
        self,
        tool: MailToolName,
        user: UserContext,
        *,
        expected: type[PayloadT],
        **arguments: Any,
    ) -> PayloadT:
        """Invoke a tool and validate the payload it returned."""
        result = await self._invoke(tool, user, arguments)
        return self._validated(result, expected, tool)

    async def _acknowledge(self, tool: MailToolName, user: UserContext, **arguments: Any) -> None:
        """Invoke a tool whose success carries no payload."""
        await self._invoke(tool, user, arguments)

    async def _invoke(self, tool: MailToolName, user: UserContext, arguments: Mapping[str, Any]) -> CallToolResult:
        """Send one tool call, refusing another mailbox and decoding failures."""
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
        structured = result.structuredContent
        if structured is None:
            raise MailToolProtocolError(f"mail tool {tool.value!r} returned no structured content")
        try:
            return expected.model_validate(structured)
        except ValueError as error:
            raise MailToolProtocolError(
                f"mail tool {tool.value!r} returned an unusable {expected.__name__}"
            ) from error

    @staticmethod
    def _text_of(result: CallToolResult) -> str:
        """Return the text a failing tool reported."""
        return " ".join(item.text for item in result.content if isinstance(item, TextContent)).strip()
