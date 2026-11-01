"""Per-skill alias-scoped view over one server's shared wiki tools object.

Two sibling skills on the same server share one connection and one underlying
dialect object (so the connection pool and any dialect-internal state stay
single), but each skill's manifest declares its own subset of
:class:`WikiToolName` aliases. Handing the raw shared object to every skill
would silently let a read-only skill invoke writes the server supports but the
skill's own manifest never declared. This wrapper is what
:meth:`WikiToolsProvider.build_for_skill` actually returns: it forwards each
domain-port call to the shared object only if the skill's own alias set allows
it, and raises an explicit domain error otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ygo74.agent_runtime.domains.mcp.registry import McpSkillServerView
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.application.ports.wiki_tools import WikiTools
from ai_agent_lab.wiki.domain.operation_names import WikiToolName
from ai_agent_lab.wiki.infrastructure.mcp.errors import McpBindingError

if TYPE_CHECKING:
    from ai_agent_lab.wiki.domain.models import (
        WikiComment,
        WikiPage,
        WikiPageHistory,
        WikiPageTree,
        WikiSearchRequest,
        WikiSearchResult,
        WikiSpace,
    )


class ScopedWikiTools:
    """Restrict a shared :class:`WikiTools` object to one skill's own aliases.

    Args:
        tool_name: Manifest identity of the skill this scope belongs to.
        delegate: The shared, per-server dialect object every sibling skill routes through.
        view: Runtime alias scope and lifecycle of the selected connection.
    """

    def __init__(
        self,
        tool_name: str,
        delegate: WikiTools,
        view: McpSkillServerView,
    ) -> None:
        self._tool_name = tool_name
        self._delegate = delegate
        self._view = view

    def _require(self, operation: WikiToolName) -> None:
        """Reject a call to an operation this skill's manifest does not declare."""
        if operation.value not in self._view.tools:
            raise McpBindingError(
                f"skill {self._tool_name!r} does not declare MCP tool alias {operation.value!r}"
            )

    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult:
        """Return the page references matching a structured query."""
        self._require(WikiToolName.SEARCH_WIKI)
        return await self._delegate.search(request, user)

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        """Return one complete page, body included."""
        self._require(WikiToolName.GET_PAGE)
        return await self._delegate.get_page(page_id, user)

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        """Return the direct children of a page, one level deep."""
        self._require(WikiToolName.GET_PAGE_CHILDREN)
        return await self._delegate.get_children(page_id, user)

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        """Return the spaces this user may read."""
        self._require(WikiToolName.LIST_SPACES)
        return await self._delegate.list_spaces(user)

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        """Return the comments attached to a page."""
        self._require(WikiToolName.GET_COMMENTS)
        return await self._delegate.get_comments(page_id, user)

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        """Return the revision history of a page, newest first."""
        self._require(WikiToolName.GET_PAGE_HISTORY)
        return await self._delegate.get_history(page_id, user)

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
        self._require(WikiToolName.CREATE_PAGE)
        return await self._delegate.create_page(space_key, title, body, user, parent_id=parent_id)

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
        self._require(WikiToolName.UPDATE_PAGE)
        return await self._delegate.update_page(
            page_id, body, user, title=title, expected_version=expected_version
        )

    async def delete_page(self, page_id: str, user: UserContext) -> None:
        """Delete a page."""
        self._require(WikiToolName.DELETE_PAGE)
        await self._delegate.delete_page(page_id, user)

    async def add_comment(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        parent_comment_id: str | None = None,
    ) -> WikiComment:
        """Post a comment on a page and return it as stored."""
        self._require(WikiToolName.ADD_COMMENT)
        return await self._delegate.add_comment(page_id, body, user, parent_comment_id=parent_comment_id)
