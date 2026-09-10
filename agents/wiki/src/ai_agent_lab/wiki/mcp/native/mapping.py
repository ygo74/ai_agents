"""Translation of protocol payloads into wiki domain models.

This is the boundary where third-party text becomes untrusted content. Every free
string a server returns - titles, bodies, excerpts, space names, comments, author
display names, labels, version messages - is wrapped on the way in, without
exception and without judgement about which of them "look safe".

Doing it here rather than at the point of use is what makes it verifiable: a
string that reached a skill unwrapped would have crossed the boundary unnoticed,
and nothing downstream could tell.
"""

from __future__ import annotations

from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.wiki.domain.enums import WikiContentFormat, WikiPageStatus
from ai_agent_lab.wiki.domain.models import (
    WikiAuthor,
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageReference,
    WikiPageTree,
    WikiPageVersion,
    WikiSearchResult,
    WikiSpace,
)
from ai_agent_lab.wiki.wiki_errors import WikiToolProtocolError
from wiki_mcp.protocol import payloads as wire


class WikiWireMapper:
    """Turns protocol payloads into domain models, fencing untrusted text."""

    def search_result(self, payload: wire.SearchResult) -> WikiSearchResult:
        """Map a search result."""
        return self._built(
            WikiSearchResult,
            references=tuple(self.reference(item) for item in payload.references),
            total_count=payload.total_count,
            truncated=payload.truncated,
        )

    def reference(self, payload: wire.PageReference) -> WikiPageReference:
        """Map one search hit."""
        return self._built(
            WikiPageReference,
            page_id=payload.page_id,
            space_key=payload.space_key,
            title=untrusted(payload.title, UntrustedOrigin.WIKI_PAGE_TITLE),
            excerpt=(
                None
                if payload.excerpt is None
                else untrusted(payload.excerpt, UntrustedOrigin.WIKI_PAGE_EXCERPT)
            ),
            status=WikiPageStatus(payload.status.value),
            last_modified_at=payload.last_modified_at,
            version=payload.version,
            url=payload.url,
        )

    def page(self, payload: wire.Page) -> WikiPage:
        """Map one complete page."""
        return self._built(
            WikiPage,
            page_id=payload.page_id,
            space_key=payload.space_key,
            title=untrusted(payload.title, UntrustedOrigin.WIKI_PAGE_TITLE),
            body=untrusted(payload.body, UntrustedOrigin.WIKI_PAGE_BODY),
            body_format=WikiContentFormat(payload.body_format.value),
            status=WikiPageStatus(payload.status.value),
            parent_id=payload.parent_id,
            labels=tuple(untrusted(label, UntrustedOrigin.WIKI_LABEL) for label in payload.labels),
            created_at=payload.created_at,
            created_by=self.author(payload.created_by),
            last_modified_at=payload.last_modified_at,
            last_modified_by=self.author(payload.last_modified_by),
            version=payload.version,
            url=payload.url,
        )

    def tree(self, payload: wire.PageTree) -> WikiPageTree:
        """Map the children of a page."""
        return self._built(
            WikiPageTree,
            parent_id=payload.parent_id,
            children=tuple(self.reference(item) for item in payload.children),
        )

    def spaces(self, payload: wire.SpaceList) -> tuple[WikiSpace, ...]:
        """Map the spaces a caller may read."""
        return tuple(self.space(item) for item in payload.spaces)

    def space(self, payload: wire.Space) -> WikiSpace:
        """Map one space."""
        return self._built(
            WikiSpace,
            key=payload.key,
            name=untrusted(payload.name, UntrustedOrigin.WIKI_SPACE_NAME),
            is_personal=payload.is_personal,
            homepage_id=payload.homepage_id,
        )

    def comments(self, payload: wire.CommentList) -> tuple[WikiComment, ...]:
        """Map the comments of a page."""
        return tuple(self.comment(item) for item in payload.comments)

    def comment(self, payload: wire.Comment) -> WikiComment:
        """Map one comment."""
        return self._built(
            WikiComment,
            comment_id=payload.comment_id,
            page_id=payload.page_id,
            body=untrusted(payload.body, UntrustedOrigin.WIKI_COMMENT_BODY),
            body_format=WikiContentFormat(payload.body_format.value),
            author=self.author(payload.author),
            created_at=payload.created_at,
            parent_comment_id=payload.parent_comment_id,
            is_resolved=payload.is_resolved,
        )

    def history(self, payload: wire.PageHistory) -> WikiPageHistory:
        """Map a revision history, ordering it newest first.

        The domain requires that order because callers read the first entry as
        the current revision. A server that returned the history the other way
        round is not wrong on the wire, so it is sorted here rather than refused.
        """
        if not payload.versions:
            raise WikiToolProtocolError(f"history of page {payload.page_id!r} carries no revision")
        versions = sorted(
            (self.version(item) for item in payload.versions),
            key=lambda item: item.version,
            reverse=True,
        )
        return self._built(WikiPageHistory, page_id=payload.page_id, versions=tuple(versions))

    def version(self, payload: wire.PageVersion) -> WikiPageVersion:
        """Map one history entry."""
        return self._built(
            WikiPageVersion,
            version=payload.version,
            modified_at=payload.modified_at,
            modified_by=self.author(payload.modified_by),
            message=(
                None
                if payload.message is None
                else untrusted(payload.message, UntrustedOrigin.WIKI_VERSION_MESSAGE)
            ),
            is_minor_edit=payload.is_minor_edit,
        )

    def author(self, payload: wire.Author | None) -> WikiAuthor | None:
        """Map an author, tolerating one the server did not name."""
        if payload is None:
            return None
        return self._built(
            WikiAuthor,
            account_id=payload.account_id,
            display_name=(
                None
                if payload.display_name is None
                else untrusted(payload.display_name, UntrustedOrigin.WIKI_AUTHOR_NAME)
            ),
        )

    @staticmethod
    def _built[ModelT](model: type[ModelT], **fields: object) -> ModelT:
        """Build a domain model, reporting a payload the domain refuses.

        The domain has invariants the wire does not - a page cannot be modified
        before it was created, a history cannot repeat a version. A server
        breaking one is a protocol failure, not a crash.
        """
        try:
            return model(**fields)
        except ValueError as error:
            raise WikiToolProtocolError(
                f"the wiki server returned an unusable {model.__name__}: {error}"
            ) from error
