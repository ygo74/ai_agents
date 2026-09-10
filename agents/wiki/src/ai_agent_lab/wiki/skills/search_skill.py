"""Finding documentation, and reading what was found."""

from __future__ import annotations

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.domain.errors import EmptySearchRequestError
from ai_agent_lab.wiki.domain.models import (
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageTree,
    WikiSearchRequest,
    WikiSearchResult,
    WikiSpace,
)
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.tools_port import WikiReadTools


class DocumentationSearchSkill:
    """Finds pages, and hands back what a wiki server returned.

    It is deliberately thin. Retrieval belongs to the MCP layer, and a search
    that added ranking of its own would make results differ between servers for
    reasons nobody could see. What it does own is the refusal below.
    """

    def __init__(self, wiki_tools: WikiReadTools) -> None:
        self._wiki_tools = wiki_tools

    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult:
        """Return the pages matching a query.

        A request constraining nothing at all asks for the entire wiki. A server
        would answer it with an arbitrary page of results that look exactly like
        an answer, so it is refused here instead - with a message telling the
        model what to add.
        """
        user.require_permission(WikiPermission.READ)
        if request.is_empty:
            raise EmptySearchRequestError
        return await self._wiki_tools.search(request, user)

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        """Return one complete page."""
        user.require_permission(WikiPermission.READ)
        return await self._wiki_tools.get_page(page_id, user)

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        """Return the direct children of a page."""
        user.require_permission(WikiPermission.READ)
        return await self._wiki_tools.get_children(page_id, user)

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        """Return the spaces this user may read."""
        user.require_permission(WikiPermission.READ)
        return await self._wiki_tools.list_spaces(user)

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        """Return the comments attached to a page."""
        user.require_permission(WikiPermission.READ)
        return await self._wiki_tools.get_comments(page_id, user)

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        """Return the revision history of a page."""
        user.require_permission(WikiPermission.READ)
        return await self._wiki_tools.get_history(page_id, user)
