"""Finding documentation, and reading what was found."""

from __future__ import annotations

import logging

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

_logger = logging.getLogger(__name__)


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
            _logger.warning("Empty search request rejected for user=%s", user.user_id)
            raise EmptySearchRequestError
        _logger.info(
            "Searching wiki: query='%s', space_keys=%s, user=%s",
            request.text,
            request.space_keys,
            user.user_id,
        )
        result = await self._wiki_tools.search(request, user)
        _logger.info("Wiki search returned %d hits (total=%d)", len(result.references), result.total_count)
        _logger.debug("Search results references: %s", [r.page_id for r in result.references])
        return result

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        """Return one complete page."""
        user.require_permission(WikiPermission.READ)
        _logger.info("Fetching wiki page id='%s' for user=%s", page_id, user.user_id)
        page = await self._wiki_tools.get_page(page_id, user)
        _logger.info(
            "Fetched wiki page id='%s', version=%d (title_length=%d)",
            page.page_id,
            page.version,
            page.title.length,
        )
        return page

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        """Return the direct children of a page."""
        user.require_permission(WikiPermission.READ)
        _logger.info("Fetching children for wiki page id='%s'", page_id)
        tree = await self._wiki_tools.get_children(page_id, user)
        _logger.info("Found %d children for page id='%s'", len(tree.children), page_id)
        return tree

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        """Return the spaces this user may read."""
        user.require_permission(WikiPermission.READ)
        _logger.info("Listing wiki spaces for user=%s", user.user_id)
        spaces = await self._wiki_tools.list_spaces(user)
        _logger.info("Found %d accessible space(s) for user=%s", len(spaces), user.user_id)
        _logger.debug("Spaces: %s", [s.key for s in spaces])
        return spaces

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        """Return the comments attached to a page."""
        user.require_permission(WikiPermission.READ)
        _logger.info("Fetching comments for wiki page id='%s'", page_id)
        comments = await self._wiki_tools.get_comments(page_id, user)
        _logger.info("Found %d comment(s) on page id='%s'", len(comments), page_id)
        return comments

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        """Return the revision history of a page."""
        user.require_permission(WikiPermission.READ)
        _logger.info("Fetching revision history for wiki page id='%s'", page_id)
        history = await self._wiki_tools.get_history(page_id, user)
        _logger.info("Found %d version(s) for page id='%s'", len(history.versions), page_id)
        return history
