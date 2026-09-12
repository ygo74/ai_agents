"""Answering a question from the documentation, and only from it.

This is the capability the agent exists for, and the one most easily done badly.
A language model asked a question about a project will produce a fluent answer
whether or not the documentation contains one; the whole value here is the
difference between "the wiki says X" and "the wiki does not say".

Three things enforce that difference, none of them a matter of asking the model
nicely:

- the answer is built only from pages actually retrieved, and every citation is
  resolved against them (:class:`WikiAnalysisMapper`);
- an answer citing nothing is reported as ungrounded, whatever the model claimed
  about itself;
- retrieving nothing at all raises rather than reaching the model, because there
  is then nothing to answer from.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.domain.errors import UngroundedAnswerError
from ai_agent_lab.wiki.domain.models import (
    WikiAnswer,
    WikiPage,
    WikiPageReference,
    WikiSearchRequest,
)
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.skills.analysis import AnswerOutput, WikiAnalysisMapper
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.question_terms import QuestionTerms
from ai_agent_lab.wiki.tools_port import WikiReadTools

_logger = logging.getLogger(__name__)

DEFAULT_PAGES_CONSULTED = 5


class DocumentationAnswerSkill:
    """Answers a question from retrieved documentation, citing its sources."""

    def __init__(
        self,
        wiki_tools: WikiReadTools,
        reasoner: TextReasoner,
        context_builder: WikiContextBuilder,
        mapper: WikiAnalysisMapper,
        instructions: str,
        *,
        question_terms: QuestionTerms | None = None,
        pages_consulted: int = DEFAULT_PAGES_CONSULTED,
    ) -> None:
        self._wiki_tools = wiki_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._mapper = mapper
        self._instructions = instructions
        self._question_terms = question_terms or QuestionTerms()
        self._pages_consulted = pages_consulted

    async def answer(
        self,
        question: str,
        user: UserContext,
        *,
        space_keys: Sequence[str] = (),
    ) -> WikiAnswer:
        """Search the wiki for a question, then answer from what was found.

        The question is reduced to its content words, and broadened if the first
        attempt finds nothing. A server ranking by relevance settles this on the
        first search; one matching terms literally would otherwise have found
        nothing because of a single incidental word, and the agent would have
        reported that the documentation is silent when it was the query that was
        wrong.
        """
        user.require_permission(WikiPermission.READ)
        _logger.info("Answering question from wiki for user=%s: '%s'", user.user_id, question)
        references = await self._retrieve(question, tuple(space_keys), user)
        if not references:
            _logger.warning("No wiki pages retrieved for question: '%s'", question)
            raise UngroundedAnswerError(question)

        _logger.info("Retrieved %d candidate page(s) for question", len(references))
        pages = [await self._wiki_tools.get_page(reference.page_id, user) for reference in references]
        return await self._answer_from(question, pages)

    async def _retrieve(
        self,
        question: str,
        space_keys: tuple[str, ...],
        user: UserContext,
    ) -> tuple[WikiPageReference, ...]:
        """Search with progressively broader queries until something matches."""
        ladder = self._question_terms.ladder(question)
        _logger.debug("Search ladder for question has %d query step(s)", len(ladder))
        for idx, text in enumerate(ladder, 1):
            _logger.debug("Ladder step %d/%d search query: '%s'", idx, len(ladder), text)
            result = await self._wiki_tools.search(
                WikiSearchRequest(text=text, space_keys=space_keys, limit=self._pages_consulted),
                user,
            )
            if result.references:
                _logger.debug("Ladder step %d matched %d reference(s)", idx, len(result.references))
                return result.references
        return ()

    async def answer_from_pages(
        self,
        question: str,
        page_ids: Sequence[str],
        user: UserContext,
    ) -> WikiAnswer:
        """Answer a question from an explicit set of pages."""
        user.require_permission(WikiPermission.READ)
        if not page_ids:
            _logger.warning("No page_ids provided to answer_from_pages for question: '%s'", question)
            raise UngroundedAnswerError(question)
        _logger.info("Answering question from %d explicit page(s) for user=%s", len(page_ids), user.user_id)
        pages = [await self._wiki_tools.get_page(page_id, user) for page_id in page_ids]
        return await self._answer_from(question, pages)

    async def _answer_from(self, question: str, pages: Sequence[WikiPage]) -> WikiAnswer:
        """Run the reasoner over the retrieved pages and map the outcome.

        The question travels in the task, which is trusted text from the
        application, while the pages travel in the untrusted context. Putting the
        question inside the context instead would have blurred the one boundary
        the envelope exists to draw.
        """
        _logger.debug("Running reasoner to answer question from %d page(s)", len(pages))
        request = ReasoningRequest(
            instructions=self._instructions,
            task=(
                f"Answer this question using only the documentation below: {question}\n\n"
                "Cite the page_id of every page you used. If the documentation does not answer "
                "the question, say so and set is_grounded to false rather than filling the gap."
            ),
            context=self._context_builder.build(pages),
        )
        output = await self._reasoner.reason(request, AnswerOutput)
        answer = self._mapper.to_answer(output, question, pages)
        _logger.info("Answer generated (is_grounded=%s, sources_count=%d)", answer.is_grounded, len(answer.sources))
        _logger.debug("Answer content: %s", answer.answer)
        return answer
