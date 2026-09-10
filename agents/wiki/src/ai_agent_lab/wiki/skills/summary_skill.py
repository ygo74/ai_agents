"""Summarisation of a page, a page tree or a set of related pages."""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.domain.models import WikiPage, WikiPageSummary
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.skills.analysis import PageSummaryOutput, WikiAnalysisMapper
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.errors import EmptyPageSelectionError
from ai_agent_lab.wiki.tools_port import WikiReadTools


class PageSummarySkill:
    """Produces a structured summary grounded in retrieved pages.

    Retrieval is delegated to the MCP layer and reasoning to the injected
    :class:`TextReasoner`, so the skill itself stays free of both transport and
    framework concerns. The reasoning instructions are injected too: they are
    delivered configuration, not code.
    """

    def __init__(
        self,
        wiki_tools: WikiReadTools,
        reasoner: TextReasoner,
        context_builder: WikiContextBuilder,
        mapper: WikiAnalysisMapper,
        instructions: str,
    ) -> None:
        self._wiki_tools = wiki_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._mapper = mapper
        self._instructions = instructions

    async def summarise_page(self, page_id: str, user: UserContext) -> WikiPageSummary:
        """Summarise a single page."""
        user.require_permission(WikiPermission.READ)
        page = await self._wiki_tools.get_page(page_id, user)
        return await self._summarise((page,), "Summarise this page.")

    async def summarise_page_with_discussion(self, page_id: str, user: UserContext) -> WikiPageSummary:
        """Summarise a page together with its comments.

        Worth having as its own capability: a comment often carries the
        objection, the decision or the correction that never made it into the
        page, and a summary of the body alone would be confidently out of date.
        """
        user.require_permission(WikiPermission.READ)
        page = await self._wiki_tools.get_page(page_id, user)
        comments = await self._wiki_tools.get_comments(page_id, user)
        request = ReasoningRequest(
            instructions=self._instructions,
            task=(
                "Summarise this page together with its discussion. Where a comment contradicts "
                "or qualifies the page, say so explicitly rather than choosing between them."
            ),
            context=self._context_builder.build_with_discussion(page, comments),
        )
        output = await self._reasoner.reason(request, PageSummaryOutput)
        return self._mapper.to_summary(output, (page,))

    async def summarise_pages(self, page_ids: Sequence[str], user: UserContext) -> WikiPageSummary:
        """Summarise an arbitrary set of related pages."""
        user.require_permission(WikiPermission.READ)
        if not page_ids:
            raise EmptyPageSelectionError("PageSummarySkill")
        pages = [await self._wiki_tools.get_page(page_id, user) for page_id in page_ids]
        return await self._summarise(tuple(pages), "Summarise these related pages.")

    async def summarise_subtree(self, page_id: str, user: UserContext) -> WikiPageSummary:
        """Summarise a page and its direct children.

        One level only. Following a whole subtree would be unbounded, and a space
        of two hundred pages would quietly become two hundred retrievals.
        """
        user.require_permission(WikiPermission.READ)
        root = await self._wiki_tools.get_page(page_id, user)
        tree = await self._wiki_tools.get_children(page_id, user)
        children = [
            await self._wiki_tools.get_page(reference.page_id, user) for reference in tree.children
        ]
        return await self._summarise(
            (root, *children),
            "Summarise this page and the pages below it, as one body of documentation.",
        )

    async def _summarise(self, pages: Sequence[WikiPage], task: str) -> WikiPageSummary:
        """Run the reasoner over the given pages and map the outcome."""
        request = ReasoningRequest(
            instructions=self._instructions,
            task=task,
            context=self._context_builder.build(pages),
        )
        output = await self._reasoner.reason(request, PageSummaryOutput)
        return self._mapper.to_summary(output, pages)
