"""Mail MCP client speaking the contract payloads.

This implementation talks to a server that answers our own tool names with the
payloads of :mod:`ai_agent_lab.mcp.mail.payloads`: the reference server, and any
server built to match it, such as one backed by EWS or Microsoft Graph. A server
with its own shapes - the official Gmail one - gets its own implementation of
the same contract rather than a flag inside this one.

Everything the server returns is validated before it becomes a domain object,
and every piece of free text is fenced as untrusted content on the way in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp.types import CallToolResult, TextContent

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
from ai_agent_lab.infrastructure.config.mcp_binding import McpServerBinding
from ai_agent_lab.infrastructure.mcp.connection import McpConnection
from ai_agent_lab.mcp.mail.errors import (
    MailAccessDeniedError,
    MailToolProtocolError,
    MailToolUnavailableError,
    decode_failure,
)
from ai_agent_lab.mcp.mail.payloads import (
    DraftPayload,
    LabelsPayload,
    MessagePayload,
    Payload,
    SearchResultPayload,
    SendResultPayload,
    ThreadPayload,
)

REQUIRED_ALIASES = (
    "search_mail",
    "get_mail",
    "get_thread",
    "list_labels",
    "create_draft",
    "send_mail",
    "mark_read",
    "archive_mail",
    "apply_label",
    "remove_label",
)

_OWNER = "owner"


class McpMailTools:
    """Mail MCP contract served by a server speaking our payloads."""

    def __init__(
        self,
        connection: McpConnection,
        binding: McpServerBinding,
        *,
        owner_id: str,
    ) -> None:
        binding.require_aliases(REQUIRED_ALIASES)
        self._connection = connection
        self._binding = binding
        self._owner_id = owner_id

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query."""
        payload = await self._call(
            "search_mail",
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
            expected=SearchResultPayload,
        )
        return payload.to_domain()

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        payload = await self._call("get_mail", user, message_id=message_id, expected=MessagePayload)
        return payload.to_domain()

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation."""
        payload = await self._call("get_thread", user, thread_id=thread_id, expected=ThreadPayload)
        return payload.to_domain()

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        payload = await self._call("list_labels", user, expected=LabelsPayload)
        return payload.to_domain()

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        payload = await self._call(
            "create_draft",
            user,
            draft=DraftPayload.of(draft).model_dump(mode="json"),
            expected=DraftPayload,
        )
        return payload.to_domain()

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Deliver a draft to its recipients."""
        payload = await self._call(
            "send_mail",
            user,
            draft=DraftPayload.of(request.draft).model_dump(mode="json"),
            expected=SendResultPayload,
        )
        return payload.to_domain()

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread."""
        await self._acknowledge("mark_read", user, message_id=message_id, is_read=is_read)

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        await self._acknowledge("archive_mail", user, message_id=message_id)

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label to a message."""
        await self._acknowledge("apply_label", user, message_id=message_id, label_id=label_id)

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label from a message."""
        await self._acknowledge("remove_label", user, message_id=message_id, label_id=label_id)

    async def _call[PayloadT: Payload](
        self,
        alias: str,
        user: UserContext,
        *,
        expected: type[PayloadT],
        **arguments: Any,
    ) -> PayloadT:
        """Invoke a tool and validate the payload it returned."""
        result = await self._invoke(alias, user, arguments)
        return self._validated(result, expected, alias)

    async def _acknowledge(self, alias: str, user: UserContext, **arguments: Any) -> None:
        """Invoke a tool whose success carries no payload."""
        await self._invoke(alias, user, arguments)

    async def _invoke(self, alias: str, user: UserContext, arguments: Mapping[str, Any]) -> CallToolResult:
        """Send one tool call, refusing another mailbox and decoding failures."""
        self._require_owner(user)
        session = await self._connection.session()
        payload = {key: value for key, value in arguments.items() if value is not None}
        try:
            result = await session.call_tool(self._binding.remote(alias), {_OWNER: user.user_id, **payload})
        except Exception as error:
            raise MailToolUnavailableError(
                f"mail tool {alias!r} could not be called: {type(error).__name__}"
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
    def _validated[PayloadT: Payload](
        result: CallToolResult,
        expected: type[PayloadT],
        alias: str,
    ) -> PayloadT:
        """Turn the structured answer of a tool into a validated payload."""
        structured = result.structuredContent
        if structured is None:
            raise MailToolProtocolError(f"mail tool {alias!r} returned no structured content")
        try:
            return expected.model_validate(structured)
        except ValueError as error:
            raise MailToolProtocolError(f"mail tool {alias!r} returned an unusable {expected.__name__}") from error

    @staticmethod
    def _text_of(result: CallToolResult) -> str:
        """Return the text a failing tool reported."""
        return " ".join(item.text for item in result.content if isinstance(item, TextContent)).strip()
