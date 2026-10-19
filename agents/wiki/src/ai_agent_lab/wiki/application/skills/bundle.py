"""The assembled skill set exposed to Wiki application services."""

from __future__ import annotations

from dataclasses import dataclass

from ai_agent_lab.wiki.application.skills.answer_skill import DocumentationAnswerSkill
from ai_agent_lab.wiki.application.skills.authoring_skill import PageAuthoringSkill
from ai_agent_lab.wiki.application.skills.comment_skill import PageCommentSkill
from ai_agent_lab.wiki.application.skills.drafting_skill import PageDraftingSkill
from ai_agent_lab.wiki.application.skills.freshness_skill import PageFreshnessSkill
from ai_agent_lab.wiki.application.skills.search_skill import DocumentationSearchSkill
from ai_agent_lab.wiki.application.skills.summary_skill import PageSummarySkill


@dataclass(frozen=True, slots=True)
class WikiSkills:
    """The domain capabilities of the Wiki Agent."""

    search: DocumentationSearchSkill
    summary: PageSummarySkill
    answer: DocumentationAnswerSkill
    freshness: PageFreshnessSkill
    drafting: PageDraftingSkill
    authoring: PageAuthoringSkill
    comment: PageCommentSkill
