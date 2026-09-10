"""Reasoner output models and their translation into domain models.

The shape a language model is asked to produce is a technical concern, kept apart
from the domain vocabulary. This module owns that shape and the mapping, so every
wiki skill validates model output the same way.

Mapping is where grounding is enforced: a result may only cite pages that were
part of the analysed context. Otherwise a planted instruction inside a page could
have the model attribute a claim to a page nobody retrieved, and the user would
read it as a sourced fact.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.wiki.domain.models import (
    WikiAnswer,
    WikiPage,
    WikiPageSummary,
    WikiSourceReference,
)
from ai_agent_lab.wiki.skills.errors import UngroundedWikiResultError


class ReasonerOutput(BaseModel):
    """Base class for the structures a reasoner is asked to return."""

    model_config = ConfigDict(extra="ignore")


class PageSummaryOutput(ReasonerOutput):
    """Structured summary of one or several pages."""

    summary: str
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    cited_page_ids: list[str] = Field(default_factory=list)


class AnswerOutput(ReasonerOutput):
    """An answer the model believes the documentation supports."""

    answer: str
    is_grounded: bool = Field(
        default=True,
        description="False when the retrieved pages do not actually answer the question.",
    )
    uncertainties: list[str] = Field(default_factory=list)
    cited_page_ids: list[str] = Field(default_factory=list)


class DocumentationGapOutput(ReasonerOutput):
    """One thing the documentation does not cover."""

    subject: str
    reason: str = ""


class DocumentationGapsOutput(ReasonerOutput):
    """The gaps found between an expected structure and what exists."""

    gaps: list[DocumentationGapOutput] = Field(default_factory=list)
    cited_page_ids: list[str] = Field(default_factory=list)


class WikiAnalysisMapper:
    """Turns reasoner output into domain models, enforcing grounding."""

    def to_summary(self, output: PageSummaryOutput, pages: Sequence[WikiPage]) -> WikiPageSummary:
        """Build a domain summary grounded in the analysed pages."""
        return WikiPageSummary(
            summary=output.summary.strip(),
            key_points=tuple(self._clean(output.key_points)),
            decisions=tuple(self._clean(output.decisions)),
            open_questions=tuple(self._clean(output.open_questions)),
            sources=self._sources(output.cited_page_ids, pages),
        )

    def to_answer(self, output: AnswerOutput, question: str, pages: Sequence[WikiPage]) -> WikiAnswer:
        """Build a domain answer grounded in the analysed pages.

        An answer citing nothing is reported as ungrounded whatever the model
        said about itself. The documentation is the only thing this agent is
        allowed to answer from, so an uncited paragraph is a guess wearing the
        clothes of an answer.
        """
        sources = self._sources(output.cited_page_ids, pages)
        return WikiAnswer(
            question=question,
            answer=output.answer.strip(),
            is_grounded=output.is_grounded and bool(sources),
            uncertainties=tuple(self._clean(output.uncertainties)),
            sources=sources,
        )

    def _sources(
        self,
        cited_page_ids: Iterable[str],
        pages: Sequence[WikiPage],
    ) -> tuple[WikiSourceReference, ...]:
        """Resolve cited identifiers against the pages actually retrieved.

        Duplicates are collapsed and order is preserved, so a model citing the
        same page five times produces one reference rather than five.
        """
        by_id = {page.page_id: page for page in pages}
        resolved: dict[str, WikiSourceReference] = {}
        for cited in cited_page_ids:
            identifier = cited.strip()
            if not identifier:
                continue
            page = by_id.get(identifier)
            if page is None:
                raise UngroundedWikiResultError(identifier)
            resolved.setdefault(identifier, self.reference_of(page))
        return tuple(resolved.values())

    @staticmethod
    def reference_of(page: WikiPage) -> WikiSourceReference:
        """Build the citation of a page."""
        return WikiSourceReference(
            page_id=page.page_id,
            space_key=page.space_key,
            version=page.version,
            url=page.url,
        )

    @staticmethod
    def _clean(values: Iterable[str]) -> list[str]:
        """Drop blank entries and trim the rest."""
        return [value.strip() for value in values if value.strip()]
