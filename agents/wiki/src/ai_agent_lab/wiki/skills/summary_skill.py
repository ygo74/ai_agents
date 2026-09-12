"""Summarisation of a page, a page tree or a set of related pages."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.domain.models import WikiPage, WikiPageSummary
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.skills.analysis import PageSummaryOutput, WikiAnalysisMapper
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.errors import EmptyPageSelectionError
from ai_agent_lab.wiki.tools_port import WikiReadTools

_logger = logging.getLogger(__name__)


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
        _logger.info("Summarising page id='%s' for user=%s", page_id, user.user_id)
        page = await self._wiki_tools.get_page(page_id, user)
        return await self._summarise((page,), "Summarise this page.")

    async def summarise_page_with_discussion(self, page_id: str, user: UserContext) -> WikiPageSummary:
        """Summarise a page together with its comments.

        Worth having as its own capability: a comment often carries the
        objection, the decision or the correction that never made it into the
        page, and a summary of the body alone would be confidently out of date.
        """
        user.require_permission(WikiPermission.READ)
        _logger.info("Summarising page id='%s' with discussion for user=%s", page_id, user.user_id)
        page = await self._wiki_tools.get_page(page_id, user)
        comments = await self._wiki_tools.get_comments(page_id, user)
        _logger.debug("Page id='%s' has %d comments to include in summary", page_id, len(comments))
        request = ReasoningRequest(
            instructions=self._instructions,
            task=(
                "Summarise this page together with its discussion. Where a comment contradicts "
                "or qualifies the page, say so explicitly rather than choosing between them."
            ),
            context=self._context_builder.build_with_discussion(page, comments),
        )
        output = await self._reasoner.reason(request, PageSummaryOutput)
        summary = self._mapper.to_summary(output, (page,))
        _logger.info(
            "Generated summary with discussion for page id='%s' (%d key points)",
            page_id,
            len(summary.key_points),
        )
        return summary

    async def summarise_pages(self, page_ids: Sequence[str], user: UserContext) -> WikiPageSummary:
        """Summarise an arbitrary set of related pages."""
        user.require_permission(WikiPermission.READ)
        if not page_ids:
            _logger.warning("Empty page selection for summarise_pages from user=%s", user.user_id)
            raise EmptyPageSelectionError("PageSummarySkill")
        _logger.info("Summarising %d pages (%s) for user=%s", len(page_ids), page_ids, user.user_id)
        pages = [await self._wiki_tools.get_page(page_id, user) for page_id in page_ids]
        return await self._summarise(tuple(pages), "Summarise these related pages.")

    async def summarise_subtree(self, page_id: str, user: UserContext) -> WikiPageSummary:
        """Summarise a page and its direct children.

        One level only. Following a whole subtree would be unbounded, and a space
        of two hundred pages would quietly become two hundred retrievals.
        """
        user.require_permission(WikiPermission.READ)
        _logger.info("Summarising subtree rooted at page id='%s'", page_id)
        root = await self._wiki_tools.get_page(page_id, user)
        tree = await self._wiki_tools.get_children(page_id, user)
        children = [await self._wiki_tools.get_page(reference.page_id, user) for reference in tree.children]
        _logger.debug("Subtree at '%s' has %d child page(s)", page_id, len(children))
        return await self._summarise(
            (root, *children),
            "Summarise this page and the pages below it, as one body of documentation.",
        )

    async def _summarise(self, pages: Sequence[WikiPage], task: str) -> WikiPageSummary:
        """Run the reasoner over the given pages and map the outcome."""
        _logger.debug("Building reasoning request for %d page(s), task: %s", len(pages), task)
        request = ReasoningRequest(
            instructions=self._instructions,
            task=task,
            context=self._context_builder.build(pages),
        )
        output = await self._reasoner.reason(request, PageSummaryOutput)
        summary = self._mapper.to_summary(output, pages)
        _logger.info(
            "Generated summary for %d page(s) (%d key points, %d sources)",
            len(pages),
            len(summary.key_points),
            len(summary.sources),
        )
        return summary
