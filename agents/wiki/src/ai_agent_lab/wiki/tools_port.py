"""Contracts of the wiki MCP tool surface.

This module declares what a wiki MCP server offers, using only domain types. It
contains no implementation and no protocol knowledge: whether the server is
backed by Confluence Cloud, Confluence Data Center, Notion, XWiki or a fixture is
invisible here, and must stay invisible to every caller.

That invisibility is the whole point of this file. The lab runs against
Confluence Cloud and the target deployment is Confluence Data Center; the two
differ in authentication, in REST version and in half their endpoints, and none
of that reaches above this line.

The surface is split into focused protocols so that a skill depends only on the
capabilities it actually uses. :class:`WikiTools` composes them for
implementations and for the composition root.

Every method takes a :class:`UserContext`. A wiki restricts pages and spaces per
person, so a call without an identity would either return nothing useful or, far
worse, return what a service account can see rather than what the user can.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.domain.models import (
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageTree,
    WikiSearchRequest,
    WikiSearchResult,
    WikiSpace,
)


@runtime_checkable
class WikiReadTools(Protocol):
    """Read-only access to a wiki."""

    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult:
        """Return the page references matching a structured query.

        References rather than whole pages are returned so that a broad query
        does not pull entire bodies into the conversation.
        """
        ...

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        """Return one complete page, body included.

        Raises:
            WikiNotFoundError: no such page.
            WikiAccessDeniedError: the wiki refused the access for this user.
        """
        ...

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        """Return the direct children of a page, one level deep.

        Raises:
            WikiNotFoundError: no such page.
            WikiAccessDeniedError: the wiki refused the access for this user.
        """
        ...

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        """Return the spaces this user may read."""
        ...

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        """Return the comments attached to a page.

        Raises:
            WikiNotFoundError: no such page.
            WikiAccessDeniedError: the wiki refused the access for this user.
        """
        ...

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        """Return the revision history of a page, newest first.

        Metadata only: who changed the page, when, and the note they left. The
        content of past revisions is deliberately not offered, because retrieving
        old bodies is how a context window disappears.

        Raises:
            WikiNotFoundError: no such page.
            WikiAccessDeniedError: the wiki refused the access for this user.
        """
        ...


@runtime_checkable
class WikiAuthoringTools(Protocol):
    """Creation and modification of pages."""

    async def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        user: UserContext,
        *,
        parent_id: str | None = None,
    ) -> WikiPage:
        """Create a page and return it as the wiki stored it.

        The page becomes visible to everyone who can read the space, attributed
        to the calling user.
        """
        ...

    async def update_page(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        title: str | None = None,
        expected_version: int | None = None,
    ) -> WikiPage:
        """Replace the body of a page and return the new revision.

        ``expected_version`` guards against a lost update. Between the moment the
        agent read a page and the moment it writes one back, a person may have
        edited it; without the guard the agent would silently discard their work.
        A server that supports optimistic concurrency must refuse the write when
        the version moved on.

        This is destructive. Callers must have obtained an explicit user
        confirmation before invoking it.
        """
        ...

    async def delete_page(self, page_id: str, user: UserContext) -> None:
        """Delete a page.

        This is irreversible from the agent's point of view. Callers must have
        obtained an explicit user confirmation before invoking it.
        """
        ...


@runtime_checkable
class WikiCommentTools(Protocol):
    """Discussion attached to a page."""

    async def add_comment(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        parent_comment_id: str | None = None,
    ) -> WikiComment:
        """Post a comment on a page and return it as stored.

        The comment is attributed to the calling user and is visible to everyone
        who can read the page.
        """
        ...


@runtime_checkable
class WikiTools(
    WikiReadTools,
    WikiAuthoringTools,
    WikiCommentTools,
    Protocol,
):
    """The complete wiki MCP surface."""
