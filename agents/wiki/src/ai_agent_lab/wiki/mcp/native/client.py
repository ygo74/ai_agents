"""Wiki MCP client for a server speaking the wiki protocol.

This dialect talks to a server that answers the tool names of
:mod:`wiki_mcp.protocol` with the protocol payloads: the reference server, and
any server built to match it. A server with its own shapes - `mcp-atlassian` -
gets its own dialect rather than a flag inside this one.

Everything the server returns is validated before it becomes a domain object, and
:class:`WikiWireMapper` fences every piece of free text as untrusted content on
the way in.

Unlike the mail equivalent, this client does **not** refuse calls made for
another account. A mailbox belongs to one person, so asking for somebody else's
is always a mistake; a wiki is shared, and the server is the only thing that
knows which pages a given account may see. The account travels with every call
and the server decides. Second-guessing it here would either duplicate its rules
badly or forbid legitimate reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp.types import CallToolResult, TextContent

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.domain.models import (
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageTree,
    WikiSearchRequest,
    WikiSearchResult,
    WikiSpace,
)
from ai_agent_lab.wiki.mcp.binding import McpServerBinding
from ai_agent_lab.wiki.mcp.connection import McpConnection
from ai_agent_lab.wiki.mcp.native.mapping import WikiWireMapper
from ai_agent_lab.wiki.wiki_errors import (
    WikiToolProtocolError,
    WikiToolUnavailableError,
    decode_failure,
)
from wiki_mcp.protocol import payloads as wire
from wiki_mcp.protocol.tools import WikiToolName

# Every tool name this dialect knows how to call. A binding names the ones it
# serves; this is the whole vocabulary, kept for reference and for tests.
ALL_ALIASES = tuple(name.value for name in WikiToolName)

_ACCOUNT = "account"


class McpWikiTools:
    """Wiki tools served by a server speaking the wiki protocol."""

    def __init__(
        self,
        connection: McpConnection,
        binding: McpServerBinding,
        *,
        mapper: WikiWireMapper | None = None,
    ) -> None:
        # Only the tools of the capabilities the binding actually declares. A
        # server serving five of the ten is a normal thing - a read-only
        # deployment is exactly that - and demanding names for the five it does
        # not serve would refuse a binding that is entirely correct.
        binding.require_aliases(capability.value for capability in binding.capabilities)
        self._connection = connection
        self._binding = binding
        self._mapper = mapper or WikiWireMapper()

    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult:
        """Return the page references matching a structured query."""
        payload = await self._call(
            WikiToolName.SEARCH_WIKI,
            user,
            text=request.text or None,
            space_keys=list(request.space_keys),
            labels=list(request.labels),
            title_contains=request.title_contains or None,
            modified_after=None if request.modified_after is None else request.modified_after.isoformat(),
            modified_before=None if request.modified_before is None else request.modified_before.isoformat(),
            statuses=[status.value for status in request.statuses],
            sort_order=request.sort_order.value,
            limit=request.limit,
            expected=wire.SearchResult,
        )
        return self._mapper.search_result(payload)

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        """Return one complete page."""
        payload = await self._call(WikiToolName.GET_PAGE, user, page_id=page_id, expected=wire.Page)
        return self._mapper.page(payload)

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        """Return the direct children of a page."""
        payload = await self._call(
            WikiToolName.GET_PAGE_CHILDREN, user, page_id=page_id, expected=wire.PageTree
        )
        return self._mapper.tree(payload)

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        """Return the spaces this user may read."""
        payload = await self._call(WikiToolName.LIST_SPACES, user, expected=wire.SpaceList)
        return self._mapper.spaces(payload)

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        """Return the comments attached to a page."""
        payload = await self._call(
            WikiToolName.GET_COMMENTS, user, page_id=page_id, expected=wire.CommentList
        )
        return self._mapper.comments(payload)

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        """Return the revision history of a page."""
        payload = await self._call(
            WikiToolName.GET_PAGE_HISTORY, user, page_id=page_id, expected=wire.PageHistory
        )
        return self._mapper.history(payload)

    async def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        user: UserContext,
        *,
        parent_id: str | None = None,
    ) -> WikiPage:
        """Create a page and return it as the wiki stored it."""
        payload = await self._call(
            WikiToolName.CREATE_PAGE,
            user,
            space_key=space_key,
            title=title,
            body=body,
            parent_id=parent_id,
            expected=wire.Page,
        )
        return self._mapper.page(payload)

    async def update_page(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        title: str | None = None,
        expected_version: int | None = None,
    ) -> WikiPage:
        """Replace the body of a page and return the new revision."""
        payload = await self._call(
            WikiToolName.UPDATE_PAGE,
            user,
            page_id=page_id,
            body=body,
            title=title,
            expected_version=expected_version,
            expected=wire.Page,
        )
        return self._mapper.page(payload)

    async def delete_page(self, page_id: str, user: UserContext) -> None:
        """Delete a page."""
        await self._acknowledge(WikiToolName.DELETE_PAGE, user, page_id=page_id)

    async def add_comment(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        parent_comment_id: str | None = None,
    ) -> WikiComment:
        """Post a comment on a page and return it as stored."""
        payload = await self._call(
            WikiToolName.ADD_COMMENT,
            user,
            page_id=page_id,
            body=body,
            parent_comment_id=parent_comment_id,
            expected=wire.Comment,
        )
        return self._mapper.comment(payload)

    async def _call[PayloadT: wire.Payload](
        self,
        tool: WikiToolName,
        user: UserContext,
        *,
        expected: type[PayloadT],
        **arguments: Any,
    ) -> PayloadT:
        """Invoke a tool and validate the payload it returned."""
        result = await self._invoke(tool, user, arguments)
        return self._validated(result, expected, tool)

    async def _acknowledge(self, tool: WikiToolName, user: UserContext, **arguments: Any) -> None:
        """Invoke a tool whose success carries no payload."""
        await self._invoke(tool, user, arguments)

    async def _invoke(
        self,
        tool: WikiToolName,
        user: UserContext,
        arguments: Mapping[str, Any],
    ) -> CallToolResult:
        """Send one tool call, carrying the caller's identity and decoding failures.

        ``None`` arguments are dropped rather than sent. A server distinguishes
        "no title given" from "set the title to nothing", and sending the second
        when the caller meant the first would blank a page heading.
        """
        session = await self._connection.session()
        payload = {key: value for key, value in arguments.items() if value is not None}
        try:
            result = await session.call_tool(
                self._binding.remote(tool.value),
                {_ACCOUNT: user.user_id, **payload},
            )
        except Exception as error:
            raise WikiToolUnavailableError(
                f"wiki tool {tool.value!r} could not be called: {type(error).__name__}"
            ) from error
        if result.isError:
            raise decode_failure(self._text_of(result))
        return result

    @staticmethod
    def _validated[PayloadT: wire.Payload](
        result: CallToolResult,
        expected: type[PayloadT],
        tool: WikiToolName,
    ) -> PayloadT:
        """Turn the structured answer of a tool into a validated payload."""
        structured = result.structuredContent
        if structured is None:
            raise WikiToolProtocolError(f"wiki tool {tool.value!r} returned no structured content")
        try:
            return expected.model_validate(structured)
        except ValueError as error:
            raise WikiToolProtocolError(
                f"wiki tool {tool.value!r} returned an unusable {expected.__name__}"
            ) from error

    @staticmethod
    def _text_of(result: CallToolResult) -> str:
        """Return the text a failing tool reported."""
        return " ".join(item.text for item in result.content if isinstance(item, TextContent)).strip()
