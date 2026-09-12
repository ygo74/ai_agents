"""Composition of page content, with no effect on the wiki.

Drafting is deliberately a capability of its own, and deliberately harmless.
Composing a page is where a language model is genuinely useful; deciding that the
result should replace what a team wrote is not a judgement it may make.

Splitting the two also makes the confirmation meaningful. The draft is held on
the application side and the model is handed only an opaque reference, so the
content a user approves is exactly the content that reaches the wiki - the model
cannot rewrite it between the moment it is shown and the moment it is written.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, UntrustedText, untrusted
from ai_agent_lab.wiki.domain.models import WikiPage, WikiPageDraft
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.skills.analysis import PageDraftOutput
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.errors import EmptyPageContentError
from ai_agent_lab.wiki.tools_port import WikiReadTools

_SKILL = "PageDraftingSkill"

_REVISE_TASK = (
    "Revise the page below according to the instruction. Return the complete new body, "
    "not a patch and not a description of your changes. Preserve everything the instruction "
    "does not ask you to change."
)

_COMPOSE_TASK = (
    "Write a new wiki page for the request below. Return the complete body. Where the "
    "reference pages support a statement, follow them; where they do not, say that the point "
    "is open rather than inventing an answer."
)


class PageDraftingSkill:
    """Composes the body of a page without writing anything.

    Only the READ permission is required, because that is genuinely all this
    does. Requiring the authoring permission to *propose* text would stop a
    person who may read the wiki from preparing a page for somebody else to
    publish, and would gate an operation that has no effect.
    """

    def __init__(
        self,
        wiki_tools: WikiReadTools,
        reasoner: TextReasoner,
        context_builder: WikiContextBuilder,
        instructions: str,
    ) -> None:
        self._wiki_tools = wiki_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._instructions = instructions

    async def draft_new_page(
        self,
        space_key: str,
        title: str,
        request: str,
        user: UserContext,
        *,
        source_page_ids: tuple[str, ...] = (),
        parent_id: str | None = None,
    ) -> WikiPageDraft:
        """Compose a page that does not exist yet.

        The source pages are context, not authority: their content is fenced as
        untrusted, so an instruction planted in one of them is material to
        report rather than an order to obey.
        """
        user.require_permission(WikiPermission.READ)
        pages = [await self._wiki_tools.get_page(page_id, user) for page_id in source_page_ids]
        composed = await self._compose(_COMPOSE_TASK, request, tuple(pages))
        return WikiPageDraft(
            space_key=space_key,
            title=untrusted(composed.title.strip() or title, UntrustedOrigin.WIKI_PAGE_TITLE),
            body=untrusted(composed.body, UntrustedOrigin.WIKI_PAGE_BODY),
            parent_id=parent_id,
        )

    async def draft_page_revision(
        self,
        page_id: str,
        request: str,
        user: UserContext,
    ) -> WikiPageDraft:
        """Compose a replacement body for a page that already exists.

        The page is retrieved here rather than taken from the caller, for two
        reasons. The model needs the current text to revise rather than replace
        it, and the version it was composed against has to travel with the draft
        so a colleague editing the page in the meantime is not silently
        overwritten.
        """
        user.require_permission(WikiPermission.READ)
        page = await self._wiki_tools.get_page(page_id, user)
        composed = await self._compose(_REVISE_TASK, request, (page,))
        return WikiPageDraft(
            space_key=page.space_key,
            title=self._revised_title(composed, page),
            body=untrusted(composed.body, UntrustedOrigin.WIKI_PAGE_BODY),
            page_id=page.page_id,
            expected_version=page.version,
            parent_id=page.parent_id,
        )

    async def _compose(
        self,
        task: str,
        request: str,
        pages: tuple[WikiPage, ...],
    ) -> PageDraftOutput:
        """Run the reasoner and refuse an empty result."""
        composed = await self._reasoner.reason(
            ReasoningRequest(
                instructions=self._instructions,
                task=f"{task}\n\nInstruction from the user:\n{request}",
                context=self._context_builder.build(pages),
            ),
            PageDraftOutput,
        )
        if not composed.body.strip():
            raise EmptyPageContentError(_SKILL)
        return composed

    @staticmethod
    def _revised_title(composed: PageDraftOutput, page: WikiPage) -> UntrustedText:
        """Keep the existing title unless the model proposed a different one."""
        proposed = composed.title.strip()
        if not proposed or proposed == page.title.expose():
            return page.title
        return untrusted(proposed, UntrustedOrigin.WIKI_PAGE_TITLE)
