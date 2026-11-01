"""Route standalone Wiki port operations through their manifest skills."""

from __future__ import annotations

from collections.abc import Callable

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.application.ports.wiki_tools import WikiTools
from ai_agent_lab.wiki.domain.models import (
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageTree,
    WikiSearchRequest,
    WikiSearchResult,
    WikiSpace,
)
from ai_agent_lab.wiki.domain.operation_names import WikiToolName


class RoutedWikiTools:
    """Resolve each operation independently instead of choosing the first server.

    ``tools_for`` is looked up again on every call, which lets the same class
    serve two different routing needs:

    - An **operation-routing callback** (the grouped search and write skills)
      resolves a different manifest tool name per method, because each
      standalone read or write can be bound to its own server.
    - A **fixed-skill lazy callback** (a skill the manifest withdraws, built
      by :mod:`ai_agent_lab.wiki.bootstrap.skills_factory`) ignores the
      operation name entirely and always raises the same explicit error: the
      resolution itself is what stays lazy, not which server answers.

    Either way, no connection is opened and no server is chosen until a
    method is actually invoked.
    """

    def __init__(self, tools_for: Callable[[str], WikiTools]) -> None:
        self._tools_for = tools_for

    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult:
        return await self._tools_for(WikiToolName.SEARCH_WIKI.value).search(request, user)

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        return await self._tools_for(WikiToolName.GET_PAGE.value).get_page(page_id, user)

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        return await self._tools_for(WikiToolName.GET_PAGE_CHILDREN.value).get_children(page_id, user)

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        return await self._tools_for(WikiToolName.LIST_SPACES.value).list_spaces(user)

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        return await self._tools_for(WikiToolName.GET_COMMENTS.value).get_comments(page_id, user)

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        return await self._tools_for(WikiToolName.GET_PAGE_HISTORY.value).get_history(page_id, user)

    async def create_page(
        self, space_key: str, title: str, body: str, user: UserContext, *, parent_id: str | None = None
    ) -> WikiPage:
        return await self._tools_for(WikiToolName.CREATE_PAGE.value).create_page(
            space_key, title, body, user, parent_id=parent_id
        )

    async def update_page(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        title: str | None = None,
        expected_version: int | None = None,
    ) -> WikiPage:
        return await self._tools_for(WikiToolName.UPDATE_PAGE.value).update_page(
            page_id, body, user, title=title, expected_version=expected_version
        )

    async def delete_page(self, page_id: str, user: UserContext) -> None:
        await self._tools_for(WikiToolName.DELETE_PAGE.value).delete_page(page_id, user)

    async def add_comment(
        self, page_id: str, body: str, user: UserContext, *, parent_comment_id: str | None = None
    ) -> WikiComment:
        return await self._tools_for(WikiToolName.ADD_COMMENT.value).add_comment(
            page_id, body, user, parent_comment_id=parent_comment_id
        )
