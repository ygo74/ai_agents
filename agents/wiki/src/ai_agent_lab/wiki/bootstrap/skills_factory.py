"""Assembly of the reusable domain capabilities of the Wiki Agent.

The skills are built here, in one place, from collaborators supplied by the
composition root. Nothing in a skill knows where its reasoner came from, which
wiki server backs its tools, or which agentic framework will drive it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.reasoning.ports import TextReasoner

from ai_agent_lab.wiki.adapters.capabilities.read_capabilities import (
    ANSWER_FROM_WIKI,
    ASSESS_PAGE_FRESHNESS,
    SUMMARISE_PAGE,
)
from ai_agent_lab.wiki.adapters.capabilities.write_capabilities import DRAFT_PAGE_CONTENT
from ai_agent_lab.wiki.application.ports.wiki_tools import WikiTools
from ai_agent_lab.wiki.application.skills.analysis import WikiAnalysisMapper
from ai_agent_lab.wiki.application.skills.answer_skill import DocumentationAnswerSkill
from ai_agent_lab.wiki.application.skills.authoring_skill import PageAuthoringSkill
from ai_agent_lab.wiki.application.skills.bundle import WikiSkills
from ai_agent_lab.wiki.application.skills.comment_skill import PageCommentSkill
from ai_agent_lab.wiki.application.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.application.skills.drafting_skill import PageDraftingSkill
from ai_agent_lab.wiki.application.skills.freshness_skill import PageFreshnessDetector, PageFreshnessSkill
from ai_agent_lab.wiki.application.skills.gating import GatedWikiOperationRunner
from ai_agent_lab.wiki.application.skills.question_terms import QuestionTerms
from ai_agent_lab.wiki.application.skills.search_skill import DocumentationSearchSkill
from ai_agent_lab.wiki.application.skills.summary_skill import PageSummarySkill
from ai_agent_lab.wiki.bootstrap.routed_wiki_tools import RoutedWikiTools
from ai_agent_lab.wiki.domain.operation_names import WikiToolName
from ai_agent_lab.wiki.infrastructure.mcp.errors import McpBindingError

_logger = logging.getLogger(__name__)

ToolsResolver = Callable[[str], WikiTools]


def _unavailable_skill_resolver(tool_name: str) -> ToolsResolver:
    """Keep missing skills constructible; fail only when the router requests a delegate."""

    def _raise(alias: str) -> WikiTools:
        del alias
        raise McpBindingError(f"skill {tool_name!r} is not configured in this deployment's manifest")

    return _raise


class WikiSkillsFactory:
    """Builds the wiki skills from injected collaborators.

    The gated runner is injected rather than built here. It carries the
    confirmation policy, the domain gate and the audit trail of one deployment,
    and those belong to the composition root: a factory that built its own would
    be a second opinion on which operations need approving.

    ``tools_for`` resolves each skill's own tools **by that skill's own manifest
    tool name**: a reasoning skill like ``summarise_page`` keeps its own server
    throughout its whole call (search, read, and any composed analysis all
    route through the one connection ``summarise_page`` itself declares), and a
    grouped write skill like page authoring resolves ``create_page``,
    ``update_page`` and ``delete_page`` independently, because each of those
    three manifest skills can declare a different effective MCP server.
    """

    def __init__(
        self,
        *,
        tools_for: ToolsResolver,
        reasoner: TextReasoner,
        manifest: AgentManifest,
        context_builder: WikiContextBuilder,
        freshness_detector: PageFreshnessDetector,
        runner: GatedWikiOperationRunner,
        question_terms: QuestionTerms | None = None,
    ) -> None:
        self._tools_for = tools_for
        self._reasoner = reasoner
        self._manifest = manifest
        self._context_builder = context_builder
        self._freshness_detector = freshness_detector
        self._runner = runner
        self._question_terms = question_terms or QuestionTerms()

    def build(self) -> WikiSkills:
        """Assemble every skill."""
        _logger.info("Assembling 7 domain skills for Wiki Agent (search, summary, answer, freshness, "
                     "drafting, authoring, comment)...")
        mapper = WikiAnalysisMapper()
        summarise_prompt = self._prompt_of(SUMMARISE_PAGE)
        answer_prompt = self._prompt_of(ANSWER_FROM_WIKI)
        _logger.debug(
            "Prompts loaded: summarise_page=%d chars, answer_from_wiki=%d chars",
            len(summarise_prompt),
            len(answer_prompt),
        )
        search_skill = DocumentationSearchSkill(RoutedWikiTools(self._tools_of))
        _logger.debug("Built DocumentationSearchSkill")

        summary_skill = PageSummarySkill(
            self._tools_of(SUMMARISE_PAGE),
            self._reasoner,
            self._context_builder,
            mapper,
            summarise_prompt,
        )
        _logger.debug("Built PageSummarySkill")

        answer_skill = DocumentationAnswerSkill(
            self._tools_of(ANSWER_FROM_WIKI),
            self._reasoner,
            self._context_builder,
            mapper,
            answer_prompt,
            question_terms=self._question_terms,
        )
        _logger.debug("Built DocumentationAnswerSkill")

        freshness_skill = PageFreshnessSkill(
            self._tools_of(ASSESS_PAGE_FRESHNESS), self._freshness_detector
        )
        _logger.debug("Built PageFreshnessSkill")
        drafting = PageDraftingSkill(
            self._tools_of(DRAFT_PAGE_CONTENT),
            self._reasoner,
            self._context_builder,
            self._prompt_of(DRAFT_PAGE_CONTENT),
        )
        _logger.debug("Built PageDraftingSkill")
        authoring = PageAuthoringSkill(
            self._tools_of(WikiToolName.CREATE_PAGE.value),
            self._tools_of(WikiToolName.UPDATE_PAGE.value),
            self._tools_of(WikiToolName.DELETE_PAGE.value),
            self._runner,
        )
        _logger.debug("Built PageAuthoringSkill")
        comment = PageCommentSkill(self._tools_of(WikiToolName.ADD_COMMENT.value), self._runner)
        _logger.debug("Built PageCommentSkill")

        _logger.info("All domain skills successfully assembled")
        return WikiSkills(
            search=search_skill,
            summary=summary_skill,
            answer=answer_skill,
            freshness=freshness_skill,
            drafting=drafting,
            authoring=authoring,
            comment=comment,
        )

    def _tools_of(self, tool_name: str) -> WikiTools:
        """Resolve one skill's own tools, or an unavailable stand-in when unexposed.

        A deployment is free to leave a skill out of its manifest entirely -
        for example a read-only deployment never declaring ``create_page`` -
        and that must not break assembly of the skills that *are* exposed.
        Nothing is silently substituted from another server: the skill is
        simply built against a resolver that raises the moment it is actually
        invoked, exactly as a manifest-declared skill does when its own server
        is unreachable.
        """
        try:
            self._manifest.skill(tool_name)
        except KeyError:
            _logger.debug("No manifest skill found for '%s'; tools resolve lazily on first use", tool_name)
            return RoutedWikiTools(_unavailable_skill_resolver(tool_name))
        return self._tools_for(tool_name)

    def _prompt_of(self, tool_name: str) -> str:
        """Return the reasoning instructions delivered for a capability.

        A capability the deployment does not offer still needs a prompt, because
        the skill is built either way. An empty one is honest: the skill exists
        but is never reachable, and a placeholder sentence would be a prompt
        somebody could later mistake for the delivered one.
        """
        try:
            prompt = self._manifest.skill(tool_name).prompt
        except KeyError:
            _logger.debug("No manifest prompt found for skill '%s', using empty prompt", tool_name)
            return ""
        else:
            _logger.debug("Loaded prompt for skill '%s' (%d chars)", tool_name, len(prompt))
            return prompt
