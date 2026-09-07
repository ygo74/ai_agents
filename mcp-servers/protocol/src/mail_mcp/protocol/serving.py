"""The tool surface a mail MCP server exposes.

Both servers in this repository register exactly these twelve tools, with these
argument names and these payloads. Writing that once is what makes the reference
server a meaningful conformance target: if it and the Gmail server disagreed on
the shape of a tool, matching one would not mean matching the other.

A server supplies a mailbox and nothing else. Transport, argument descriptions
and failure reporting are handled here.

This module is a convenience for servers we write. A third-party server owes us
none of it: a caller adapts to whatever shapes that server already has.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from functools import wraps
from typing import Annotated, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from mail_mcp.protocol import payloads as wire
from mail_mcp.protocol.errors import AccessDeniedError, MailServerError, ProtocolError

MailboxOwner = Annotated[str, Field(description="Identifier of the mailbox owner the call acts for.")]
MessageId = Annotated[str, Field(description="Identifier of a message.")]
ThreadId = Annotated[str, Field(description="Identifier of a conversation.")]
LabelId = Annotated[str, Field(description="Identifier of a label.")]
LabelName = Annotated[str, Field(description="Name of a label, as the mailbox owner would read it.")]

_ACKNOWLEDGED = "ok"


class Mailbox(Protocol):
    """One mailbox, expressed in protocol payloads.

    Owner resolution happens before a mailbox is reached, so an implementation
    never carries identity plumbing.
    """

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
        ...

    async def get_message(self, message_id: str) -> wire.Message:
        """Return one complete message."""
        ...

    async def get_thread(self, thread_id: str) -> wire.Thread:
        """Return every message of a conversation."""
        ...

    async def list_labels(self) -> wire.Labels:
        """Return the labels available in the mailbox."""
        ...

    async def create_label(self, name: str) -> wire.CreatedLabel:
        """Make a label exist, returning whether it had to be created."""
        ...

    async def delete_label(self, label_id: str) -> None:
        """Delete a label, detaching it from every message carrying it."""
        ...

    async def create_draft(self, draft: wire.Draft) -> wire.Draft:
        """Persist a draft without delivering anything."""
        ...

    async def send(self, draft: wire.Draft) -> wire.SendResult:
        """Deliver a draft to its recipients."""
        ...

    async def set_read_state(self, message_id: str, is_read: bool) -> None:
        """Mark a message as read or unread."""
        ...

    async def archive(self, message_id: str) -> None:
        """Remove a message from the inbox without deleting it."""
        ...

    async def apply_label(self, message_id: str, label_id: str) -> None:
        """Attach a label to a message."""
        ...

    async def remove_label(self, message_id: str, label_id: str) -> None:
        """Detach a label from a message."""
        ...


class MailboxDirectory(Protocol):
    """Resolves the mailbox a call may act on.

    A server is the authority on who may read which mailbox. Keeping that
    decision here, rather than in the caller, means it holds even when the
    caller is careless or hostile.
    """

    def resolve(self, owner: str) -> Mailbox:
        """Return the mailbox of an owner, or refuse the access."""
        ...


class SingleMailbox:
    """A directory serving one mailbox, for a server authenticated as one user."""

    def __init__(self, owner: str, mailbox: Mailbox) -> None:
        self._owner = owner
        self._mailbox = mailbox

    def resolve(self, owner: str) -> Mailbox:
        """Return the mailbox, provided the caller asked for the right one."""
        if owner == self._owner:
            return self._mailbox
        raise AccessDeniedError(f"mailbox of {owner!r} is not served here")


def reporting[**P, R](tool: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Report a failure under the code the protocol defines.

    Without the code, a caller cannot tell a message that does not exist from a
    mailbox it may not read, and would be left guessing from prose.
    """

    @wraps(tool)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await tool(*args, **kwargs)
        except MailServerError as error:
            raise ToolError(error.reported()) from error

    return guarded


class MailToolSurface:
    """Registers the twelve mail tools on an MCP server."""

    def __init__(self, directory: MailboxDirectory, *, name: str) -> None:
        self._directory = directory
        self._server = FastMCP(name)
        self._register_read()
        self._register_message_writes()
        self._register_label_lifecycle()

    @property
    def server(self) -> FastMCP:
        """The MCP server carrying the tools."""
        return self._server

    def run(self) -> None:
        """Serve the tools over stdio until the client disconnects."""
        self._server.run()

    def _register_read(self) -> None:
        """Expose the tools that never change anything."""

        @self._server.tool(description="Search the mailbox and return message headers.")
        @reporting
        async def search_mail(
            owner: MailboxOwner,
            keywords: str | None = None,
            sender: str | None = None,
            recipient: str | None = None,
            subject_contains: str | None = None,
            label_ids: Sequence[str] = (),
            date_from: str | None = None,
            date_to: str | None = None,
            unread_only: bool = False,
            has_attachments: bool | None = None,
            limit: int = 20,
            sort_order: str = wire.SortOrder.NEWEST_FIRST.value,
        ) -> wire.SearchResult:
            return await self._directory.resolve(owner).search(
                keywords=keywords,
                sender=sender,
                recipient=recipient,
                subject_contains=subject_contains,
                label_ids=tuple(label_ids),
                date_from=_moment(date_from, "date_from"),
                date_to=_moment(date_to, "date_to"),
                unread_only=unread_only,
                has_attachments=has_attachments,
                limit=limit,
                sort_order=_ordering(sort_order),
            )

        @self._server.tool(description="Retrieve one complete message, body included.")
        @reporting
        async def get_mail(owner: MailboxOwner, message_id: MessageId) -> wire.Message:
            return await self._directory.resolve(owner).get_message(message_id)

        @self._server.tool(description="Retrieve every message of a conversation.")
        @reporting
        async def get_thread(owner: MailboxOwner, thread_id: ThreadId) -> wire.Thread:
            return await self._directory.resolve(owner).get_thread(thread_id)

        @self._server.tool(description="List the labels available in the mailbox.")
        @reporting
        async def list_labels(owner: MailboxOwner) -> wire.Labels:
            return await self._directory.resolve(owner).list_labels()

    def _register_message_writes(self) -> None:
        """Expose the tools that change a message."""

        @self._server.tool(description="Save a prepared message as a draft. Delivers nothing.")
        @reporting
        async def create_draft(owner: MailboxOwner, draft: wire.Draft) -> wire.Draft:
            return await self._directory.resolve(owner).create_draft(draft)

        @self._server.tool(description="Deliver a prepared message to its recipients. Irreversible.")
        @reporting
        async def send_mail(owner: MailboxOwner, draft: wire.Draft) -> wire.SendResult:
            return await self._directory.resolve(owner).send(draft)

        @self._server.tool(description="Mark a message as read or unread.")
        @reporting
        async def mark_read(owner: MailboxOwner, message_id: MessageId, is_read: bool) -> str:
            await self._directory.resolve(owner).set_read_state(message_id, is_read)
            return _ACKNOWLEDGED

        @self._server.tool(description="Remove a message from the inbox without deleting it.")
        @reporting
        async def archive_mail(owner: MailboxOwner, message_id: MessageId) -> str:
            await self._directory.resolve(owner).archive(message_id)
            return _ACKNOWLEDGED

        @self._server.tool(description="Attach a label to a message.")
        @reporting
        async def apply_label(owner: MailboxOwner, message_id: MessageId, label_id: LabelId) -> str:
            await self._directory.resolve(owner).apply_label(message_id, label_id)
            return _ACKNOWLEDGED

        @self._server.tool(description="Detach a label from a message.")
        @reporting
        async def remove_label(owner: MailboxOwner, message_id: MessageId, label_id: LabelId) -> str:
            await self._directory.resolve(owner).remove_label(message_id, label_id)
            return _ACKNOWLEDGED

    def _register_label_lifecycle(self) -> None:
        """Expose the tools that change which labels the mailbox has.

        These are separate from the message tools because they act on the
        structure of the mailbox rather than on anything in it: creating one
        affects no message, and deleting one affects every message carrying it.
        """

        @self._server.tool(
            description=(
                "Make a label exist in the mailbox, so messages can be filed under it. "
                "Returns the label; if one with that name already exists it is returned unchanged "
                "and nothing is created."
            )
        )
        @reporting
        async def create_label(owner: MailboxOwner, name: LabelName) -> wire.CreatedLabel:
            return await self._directory.resolve(owner).create_label(name)

        @self._server.tool(
            description=(
                "Delete a label from the mailbox. The label is also detached from every message "
                "carrying it. Irreversible. System labels cannot be deleted."
            )
        )
        @reporting
        async def delete_label(owner: MailboxOwner, label_id: LabelId) -> str:
            await self._directory.resolve(owner).delete_label(label_id)
            return _ACKNOWLEDGED


def _moment(value: str | None, field: str) -> datetime | None:
    """Read an ISO-8601 timestamp, refusing anything else."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ProtocolError(f"{field} is not an ISO-8601 timestamp") from error


def _ordering(value: str) -> wire.SortOrder:
    """Read a sort order, refusing anything else."""
    try:
        return wire.SortOrder(value)
    except ValueError as error:
        raise ProtocolError(f"sort_order {value!r} is not one of {[item.value for item in wire.SortOrder]}") from error
