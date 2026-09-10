"""The tool surface a wiki MCP server exposes.

Writing the registration once is what makes the reference server a meaningful
conformance target: if it and another server of ours disagreed on the shape of a
tool, matching one would not mean matching the other.

A server supplies a wiki and nothing else. Transport, argument descriptions and
failure reporting are handled here.

This module is a convenience for servers we write. A third-party server owes us
none of it: `sooperset/mcp-atlassian` has its own names and its own payloads, and
a caller adapts to those through a dialect on the agent side.

Every tool takes the account the call acts for, and the *server* resolves what
that account may read. Keeping the decision here rather than in the caller means
it holds even when the caller is careless or hostile - which matters more on a
wiki than on a mailbox, because a wiki has restrictions per space and per page.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from functools import wraps
from typing import Annotated, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from wiki_mcp.protocol import payloads as wire
from wiki_mcp.protocol.errors import ProtocolError, WikiServerError

Account = Annotated[str, Field(description="Identifier of the account the call acts for.")]
PageId = Annotated[str, Field(description="Identifier of a page.")]
SpaceKey = Annotated[str, Field(description="Short stable key of a space.")]
CommentId = Annotated[str, Field(description="Identifier of a comment.")]

_ACKNOWLEDGED = "ok"


class Wiki(Protocol):
    """One wiki, expressed in protocol payloads, for one account.

    Account resolution happens before a wiki is reached, so an implementation
    never carries identity plumbing - but it must still apply the restrictions of
    the account it was resolved for.
    """

    async def search(
        self,
        *,
        text: str | None = None,
        space_keys: Sequence[str] = (),
        labels: Sequence[str] = (),
        title_contains: str | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        statuses: Sequence[str] = (),
        sort_order: wire.SortOrder = wire.SortOrder.RELEVANCE,
        limit: int = 10,
    ) -> wire.SearchResult:
        """Return the page references matching a query."""
        ...

    async def get_page(self, page_id: str) -> wire.Page:
        """Return one complete page."""
        ...

    async def get_children(self, page_id: str) -> wire.PageTree:
        """Return the direct children of a page."""
        ...

    async def list_spaces(self) -> wire.SpaceList:
        """Return the spaces this account may read."""
        ...

    async def get_comments(self, page_id: str) -> wire.CommentList:
        """Return the comments attached to a page."""
        ...

    async def get_history(self, page_id: str) -> wire.PageHistory:
        """Return the revision history of a page, newest first."""
        ...

    async def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
    ) -> wire.Page:
        """Create a page and return it as stored."""
        ...

    async def update_page(
        self,
        page_id: str,
        body: str,
        title: str | None = None,
        expected_version: int | None = None,
    ) -> wire.Page:
        """Replace the body of a page and return the new revision."""
        ...

    async def delete_page(self, page_id: str) -> None:
        """Delete a page."""
        ...

    async def add_comment(
        self,
        page_id: str,
        body: str,
        parent_comment_id: str | None = None,
    ) -> wire.Comment:
        """Post a comment on a page and return it as stored."""
        ...


class WikiDirectory(Protocol):
    """Resolves which wiki an account reaches.

    A server is the authority on who may read what. Keeping that decision here,
    rather than in the caller, means it holds even when the caller is careless or
    hostile.
    """

    def resolve(self, account: str) -> Wiki:
        """Return the wiki as seen by an account, or refuse the access."""
        ...


def reporting[**P, R](tool: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Report a failure under the code the protocol defines.

    Without the code, a caller cannot tell a page that does not exist from a page
    it may not read, and would be left guessing from prose.
    """

    @wraps(tool)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await tool(*args, **kwargs)
        except WikiServerError as error:
            raise ToolError(error.reported()) from error

    return guarded


def _moment(value: str | None, field: str) -> datetime | None:
    """Parse an optional ISO-8601 timestamp, refusing a malformed one."""
    if value is None or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ProtocolError(f"{field} is not an ISO-8601 timestamp: {value!r}") from error


def _ordering(value: str) -> wire.SortOrder:
    """Parse a sort order, refusing one the protocol does not define."""
    try:
        return wire.SortOrder(value)
    except ValueError as error:
        accepted = ", ".join(order.value for order in wire.SortOrder)
        raise ProtocolError(f"sort_order must be one of {accepted}, got {value!r}") from error


class WikiToolSurface:
    """Registers the ten wiki tools on an MCP server."""

    def __init__(self, directory: WikiDirectory, *, name: str) -> None:
        self._directory = directory
        self._server = FastMCP(name)
        self._register_read()
        self._register_writes()

    @property
    def server(self) -> FastMCP:
        """The MCP server carrying the tools."""
        return self._server

    def run(self) -> None:
        """Serve the tools over stdio until the client disconnects."""
        self._server.run()

    def _register_read(self) -> None:
        """Expose the tools that never change anything."""

        @self._server.tool(description="Search the wiki and return page references, never bodies.")
        @reporting
        async def search_wiki(
            account: Account,
            text: str | None = None,
            space_keys: Sequence[str] = (),
            labels: Sequence[str] = (),
            title_contains: str | None = None,
            modified_after: str | None = None,
            modified_before: str | None = None,
            statuses: Sequence[str] = (),
            sort_order: str = wire.SortOrder.RELEVANCE.value,
            limit: int = 10,
        ) -> wire.SearchResult:
            return await self._directory.resolve(account).search(
                text=text,
                space_keys=tuple(space_keys),
                labels=tuple(labels),
                title_contains=title_contains,
                modified_after=_moment(modified_after, "modified_after"),
                modified_before=_moment(modified_before, "modified_before"),
                statuses=tuple(statuses),
                sort_order=_ordering(sort_order),
                limit=limit,
            )

        @self._server.tool(description="Retrieve one complete page, body included.")
        @reporting
        async def get_page(account: Account, page_id: PageId) -> wire.Page:
            return await self._directory.resolve(account).get_page(page_id)

        @self._server.tool(description="List the direct children of a page, one level deep.")
        @reporting
        async def get_page_children(account: Account, page_id: PageId) -> wire.PageTree:
            return await self._directory.resolve(account).get_children(page_id)

        @self._server.tool(description="List the spaces this account may read.")
        @reporting
        async def list_spaces(account: Account) -> wire.SpaceList:
            return await self._directory.resolve(account).list_spaces()

        @self._server.tool(description="Retrieve the comments attached to a page.")
        @reporting
        async def get_comments(account: Account, page_id: PageId) -> wire.CommentList:
            return await self._directory.resolve(account).get_comments(page_id)

        @self._server.tool(description="Retrieve the revision history of a page, newest first.")
        @reporting
        async def get_page_history(account: Account, page_id: PageId) -> wire.PageHistory:
            return await self._directory.resolve(account).get_history(page_id)

    def _register_writes(self) -> None:
        """Expose the tools that change the wiki."""

        @self._server.tool(description="Create a new page in a space.")
        @reporting
        async def create_page(
            account: Account,
            space_key: SpaceKey,
            title: str,
            body: str,
            parent_id: str | None = None,
        ) -> wire.Page:
            return await self._directory.resolve(account).create_page(space_key, title, body, parent_id)

        @self._server.tool(
            description=(
                "Replace the body of an existing page. Pass expected_version to be refused rather "
                "than overwrite an edit somebody made in the meantime."
            )
        )
        @reporting
        async def update_page(
            account: Account,
            page_id: PageId,
            body: str,
            title: str | None = None,
            expected_version: int | None = None,
        ) -> wire.Page:
            return await self._directory.resolve(account).update_page(
                page_id, body, title, expected_version
            )

        @self._server.tool(description="Delete a page from the wiki.")
        @reporting
        async def delete_page(account: Account, page_id: PageId) -> str:
            await self._directory.resolve(account).delete_page(page_id)
            return _ACKNOWLEDGED

        @self._server.tool(description="Post a comment on a page, without touching its body.")
        @reporting
        async def add_comment(
            account: Account,
            page_id: PageId,
            body: str,
            parent_comment_id: str | None = None,
        ) -> wire.Comment:
            return await self._directory.resolve(account).add_comment(page_id, body, parent_comment_id)
