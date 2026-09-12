"""Creation, replacement and removal of wiki pages.

Every operation here changes something a team relies on, so every one of them
goes through :class:`GatedWikiOperationRunner`. The skill holds no other route to
the MCP tools, which is what makes the guarantee structural rather than a matter
of remembering.

The three operations are not equally severe and are not treated as if they were.
Creating adds without removing. Replacing overwrites text people wrote, and the
previous revision survives only in a page history somebody has to go through by
hand. Deleting takes a page out of the wiki and breaks every link to it, and
nothing records which links those were.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationDetail,
    ConfirmationRequest,
)
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.models import WikiPage, WikiPageDraft
from ai_agent_lab.wiki.skills.errors import EmptyPageContentError
from ai_agent_lab.wiki.skills.gating import GatedWikiOperationRunner
from ai_agent_lab.wiki.tools_port import WikiAuthoringTools, WikiReadTools
from ai_agent_lab.wiki.wiki_errors import WikiAccessDeniedError, WikiNotFoundError

_SKILL = "PageAuthoringSkill"

_BODY_PREVIEW_CHARACTERS = 1500

_TITLES = {
    WikiToolName.CREATE_PAGE: "Create this page?",
    WikiToolName.UPDATE_PAGE: "Replace the content of this page?",
    WikiToolName.DELETE_PAGE: "Delete this page?",
}


class PageAuthoringSkill:
    """Writes pages to the wiki, never without an authorised decision."""

    def __init__(
        self,
        read_tools: WikiReadTools,
        authoring_tools: WikiAuthoringTools,
        runner: GatedWikiOperationRunner,
    ) -> None:
        self._read_tools = read_tools
        self._authoring_tools = authoring_tools
        self._runner = runner

    def requires_confirmation(self, tool: WikiToolName, user: UserContext) -> bool:
        """Whether this operation currently needs an approval."""
        return self._runner.requires_confirmation(tool, user)

    def build_create_confirmation_request(
        self,
        draft: WikiPageDraft,
        user: UserContext,
        *,
        target: str = "",
    ) -> ConfirmationRequest:
        """Describe a page creation so the user can judge it.

        The body is shown, truncated, because that is the whole point of asking:
        a person approving a page they have not read has not approved anything.
        These details reach a human and never a log or a trace.
        """
        details = [
            ConfirmationDetail(label="Space", value=draft.space_key),
            ConfirmationDetail(label="Title", value=self._title_of(draft)),
            ConfirmationDetail(label="Body", value=self._preview(draft.body.expose())),
        ]
        if draft.parent_id is not None:
            details.insert(2, ConfirmationDetail(label="Parent page", value=draft.parent_id))
        return self._runner.build_confirmation_request(
            WikiToolName.CREATE_PAGE,
            user,
            _TITLES[WikiToolName.CREATE_PAGE],
            target=target,
            details=details,
        )

    def build_update_confirmation_request(
        self,
        draft: WikiPageDraft,
        user: UserContext,
        *,
        target: str = "",
    ) -> ConfirmationRequest:
        """Describe a page replacement so the user can judge it."""
        details = [
            ConfirmationDetail(label="Page", value=draft.page_id or ""),
            ConfirmationDetail(label="Space", value=draft.space_key),
            ConfirmationDetail(label="Title", value=self._title_of(draft)),
            ConfirmationDetail(label="New body", value=self._preview(draft.body.expose())),
            ConfirmationDetail(
                label="Replaces version",
                value="unknown" if draft.expected_version is None else str(draft.expected_version),
            ),
        ]
        return self._runner.build_confirmation_request(
            WikiToolName.UPDATE_PAGE,
            user,
            _TITLES[WikiToolName.UPDATE_PAGE],
            target=target or (draft.page_id or ""),
            details=details,
        )

    async def build_delete_confirmation_request(
        self,
        page_id: str,
        user: UserContext,
    ) -> ConfirmationRequest:
        """Describe a page deletion so the user recognises what disappears.

        The page is read first so the user sees a title rather than an opaque
        identifier. A page that cannot be read is still described - by its
        identifier alone - rather than refused here: the deletion itself will
        fail on its own terms, and refusing at the confirmation stage would turn
        a wiki permission problem into an unexplained one.
        """
        details = [ConfirmationDetail(label="Page", value=page_id)]
        title = await self._title_if_readable(page_id, user)
        if title is not None:
            details.append(ConfirmationDetail(label="Title", value=title))
        return self._runner.build_confirmation_request(
            WikiToolName.DELETE_PAGE,
            user,
            _TITLES[WikiToolName.DELETE_PAGE],
            target=page_id,
            details=details,
        )

    async def create_page(
        self,
        draft: WikiPageDraft,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> WikiPage:
        """Create the page a draft describes."""
        self._require_content(draft)
        title = self._title_of(draft)
        return await self._runner.execute(
            WikiToolName.CREATE_PAGE,
            user,
            lambda: self._authoring_tools.create_page(
                draft.space_key,
                title,
                draft.body.expose(),
                user,
                parent_id=draft.parent_id,
            ),
            target_id=draft.space_key,
            request=request,
            decision=decision,
        )

    async def update_page(
        self,
        draft: WikiPageDraft,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> WikiPage:
        """Replace the body of the page a draft targets.

        ``expected_version`` travels with the draft and is passed on, so a
        colleague who edited the page between the drafting turn and this one
        causes the write to be refused instead of being silently overwritten.
        """
        self._require_content(draft)
        page_id = draft.page_id
        if page_id is None:
            raise EmptyPageContentError(_SKILL)
        title = self._title_of(draft) or None
        return await self._runner.execute(
            WikiToolName.UPDATE_PAGE,
            user,
            lambda: self._authoring_tools.update_page(
                page_id,
                draft.body.expose(),
                user,
                title=title,
                expected_version=draft.expected_version,
            ),
            target_id=page_id,
            request=request,
            decision=decision,
        )

    async def delete_page(
        self,
        page_id: str,
        user: UserContext,
        *,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> None:
        """Delete a page."""
        await self._runner.execute(
            WikiToolName.DELETE_PAGE,
            user,
            lambda: self._authoring_tools.delete_page(page_id, user),
            target_id=page_id,
            request=request,
            decision=decision,
        )

    async def _title_if_readable(self, page_id: str, user: UserContext) -> str | None:
        """Return the title of a page, or nothing when it cannot be read.

        Only a refusal or an absence is tolerated, and only to enrich a prompt.
        Anything else - an unreachable server, a malformed payload - is a real
        failure and is left to propagate rather than quietly producing a
        confirmation that looks merely terse.
        """
        try:
            page = await self._read_tools.get_page(page_id, user)
        except (WikiAccessDeniedError, WikiNotFoundError):
            return None
        return page.title.expose()

    @staticmethod
    def _require_content(draft: WikiPageDraft) -> None:
        """Refuse to write a page with nothing in it."""
        if not draft.body.expose().strip():
            raise EmptyPageContentError(_SKILL)

    @staticmethod
    def _title_of(draft: WikiPageDraft) -> str:
        """Return the title a draft carries, if any."""
        return "" if draft.title is None else draft.title.expose()

    @staticmethod
    def _preview(body: str) -> str:
        """Shorten a body so the confirmation stays readable."""
        if len(body) <= _BODY_PREVIEW_CHARACTERS:
            return body
        return body[:_BODY_PREVIEW_CHARACTERS] + "\n[...]"
