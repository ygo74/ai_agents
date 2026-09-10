"""Assembly of the reusable domain capabilities of the Wiki Agent.

The skills are built here, in one place, from collaborators supplied by the
composition root. Nothing in a skill knows where its reasoner came from, which
wiki server backs its tools, or which agentic framework will drive it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.reasoning.ports import TextReasoner
from ai_agent_lab.wiki.capabilities.read_capabilities import ANSWER_FROM_WIKI, SUMMARISE_PAGE
from ai_agent_lab.wiki.skills.analysis import WikiAnalysisMapper
from ai_agent_lab.wiki.skills.answer_skill import DocumentationAnswerSkill
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.freshness_skill import PageFreshnessDetector, PageFreshnessSkill
from ai_agent_lab.wiki.skills.question_terms import QuestionTerms
from ai_agent_lab.wiki.skills.search_skill import DocumentationSearchSkill
from ai_agent_lab.wiki.skills.summary_skill import PageSummarySkill
from ai_agent_lab.wiki.tools_port import WikiTools


@dataclass(frozen=True, slots=True)
class WikiSkills:
    """The domain capabilities of the Wiki Agent."""

    search: DocumentationSearchSkill
    summary: PageSummarySkill
    answer: DocumentationAnswerSkill
    freshness: PageFreshnessSkill


class WikiSkillsFactory:
    """Builds the wiki skills from injected collaborators."""

    def __init__(
        self,
        *,
        wiki_tools: WikiTools,
        reasoner: TextReasoner,
        manifest: AgentManifest,
        context_builder: WikiContextBuilder,
        freshness_detector: PageFreshnessDetector,
        question_terms: QuestionTerms | None = None,
    ) -> None:
        self._wiki_tools = wiki_tools
        self._reasoner = reasoner
        self._manifest = manifest
        self._context_builder = context_builder
        self._freshness_detector = freshness_detector
        self._question_terms = question_terms or QuestionTerms()

    def build(self) -> WikiSkills:
        """Assemble every skill."""
        mapper = WikiAnalysisMapper()
        return WikiSkills(
            search=DocumentationSearchSkill(self._wiki_tools),
            summary=PageSummarySkill(
                self._wiki_tools,
                self._reasoner,
                self._context_builder,
                mapper,
                self._prompt_of(SUMMARISE_PAGE),
            ),
            answer=DocumentationAnswerSkill(
                self._wiki_tools,
                self._reasoner,
                self._context_builder,
                mapper,
                self._prompt_of(ANSWER_FROM_WIKI),
                question_terms=self._question_terms,
            ),
            freshness=PageFreshnessSkill(self._wiki_tools, self._freshness_detector),
        )

    def _prompt_of(self, tool_name: str) -> str:
        """Return the reasoning instructions delivered for a capability.

        A capability the deployment does not offer still needs a prompt, because
        the skill is built either way. An empty one is honest: the skill exists
        but is never reachable, and a placeholder sentence would be a prompt
        somebody could later mistake for the delivered one.
        """
        try:
            return self._manifest.skill(tool_name).prompt
        except KeyError:
            return ""
