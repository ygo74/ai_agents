"""Read-only capabilities exposed by the Wiki Agent.

A capability binds three things: a delivered manifest, an argument schema, and
the skill that runs it. Nothing here contains business logic - that belongs to
the skills - and nothing here knows which agentic framework will expose it.
"""

from __future__ import annotations

from pydantic import BaseModel

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.registry import SkillDescriptor, SkillInvocation
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.capabilities.converters import WikiSearchRequestFactory
from ai_agent_lab.wiki.capabilities.results import WikiCommentsResult, WikiSpacesResult
from ai_agent_lab.wiki.capabilities.tool_inputs import (
    AnswerFromWikiInput,
    AssessFreshnessInput,
    NoInput,
    PageInput,
    SearchWikiInput,
    SummarisePageInput,
)
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.models import WikiSearchRequest
from ai_agent_lab.wiki.skills.answer_skill import DocumentationAnswerSkill
from ai_agent_lab.wiki.skills.freshness_skill import PageFreshnessSkill
from ai_agent_lab.wiki.skills.search_skill import DocumentationSearchSkill
from ai_agent_lab.wiki.skills.summary_skill import PageSummarySkill

SUMMARISE_PAGE = "summarise_page"
ANSWER_FROM_WIKI = "answer_from_wiki"
ASSESS_PAGE_FRESHNESS = "assess_page_freshness"

# Every capability this agent can offer, whatever a binding declares. The
# composition root filters this against what the bound server actually serves.
ALL_CAPABILITIES = (
    ANSWER_FROM_WIKI,
    WikiToolName.SEARCH_WIKI.value,
    WikiToolName.GET_PAGE.value,
    WikiToolName.GET_PAGE_CHILDREN.value,
    WikiToolName.LIST_SPACES.value,
    WikiToolName.GET_COMMENTS.value,
    WikiToolName.GET_PAGE_HISTORY.value,
    SUMMARISE_PAGE,
    ASSESS_PAGE_FRESHNESS,
)

# Which MCP capability each analysis capability cannot work without. A skill that
# summarises pages is useless against a server that cannot return one, so it is
# withdrawn rather than offered and failed.
REQUIRED_MCP_CAPABILITY = {
    ANSWER_FROM_WIKI: (WikiToolName.SEARCH_WIKI, WikiToolName.GET_PAGE),
    SUMMARISE_PAGE: (WikiToolName.GET_PAGE,),
    ASSESS_PAGE_FRESHNESS: (WikiToolName.SEARCH_WIKI, WikiToolName.GET_PAGE),
}


class WikiReadCapabilities:
    """Builds the descriptors of the capabilities that never change anything."""

    def __init__(
        self,
        manifest: AgentManifest,
        search_skill: DocumentationSearchSkill,
        summary_skill: PageSummarySkill,
        answer_skill: DocumentationAnswerSkill,
        freshness_skill: PageFreshnessSkill,
        search_request_factory: WikiSearchRequestFactory,
    ) -> None:
        self._manifest = manifest
        self._search_skill = search_skill
        self._summary_skill = summary_skill
        self._answer_skill = answer_skill
        self._freshness_skill = freshness_skill
        self._search_request_factory = search_request_factory

    def descriptors(self) -> tuple[SkillDescriptor, ...]:
        """Every read-only capability the manifest declares, in its order."""
        builders = {
            ANSWER_FROM_WIKI: self._answer,
            WikiToolName.SEARCH_WIKI.value: self._search,
            WikiToolName.GET_PAGE.value: self._get_page,
            WikiToolName.GET_PAGE_CHILDREN.value: self._get_children,
            WikiToolName.LIST_SPACES.value: self._list_spaces,
            WikiToolName.GET_COMMENTS.value: self._get_comments,
            WikiToolName.GET_PAGE_HISTORY.value: self._get_history,
            SUMMARISE_PAGE: self._summarise,
            ASSESS_PAGE_FRESHNESS: self._assess_freshness,
        }
        return tuple(
            builders[declared.tool_name]()
            for declared in self._manifest.skills
            if declared.tool_name in builders
        )

    def _bind(
        self,
        tool_name: str,
        input_model: type[BaseModel],
        invoke: SkillInvocation,
    ) -> SkillDescriptor:
        """Bind a delivered manifest to the code running the capability."""
        return SkillDescriptor.from_manifest(self._manifest.skill(tool_name), input_model, invoke)

    def _search(self) -> SkillDescriptor:
        """Find pages matching a structured query."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = SearchWikiInput.model_validate(payload.model_dump())
            request = self._search_request_factory.build(arguments)
            return await self._search_skill.search(request, user)

        return self._bind(WikiToolName.SEARCH_WIKI.value, SearchWikiInput, invoke)

    def _get_page(self) -> SkillDescriptor:
        """Retrieve one complete page."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = PageInput.model_validate(payload.model_dump())
            return await self._search_skill.get_page(arguments.page_id, user)

        return self._bind(WikiToolName.GET_PAGE.value, PageInput, invoke)

    def _get_children(self) -> SkillDescriptor:
        """List the direct children of a page."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = PageInput.model_validate(payload.model_dump())
            return await self._search_skill.get_children(arguments.page_id, user)

        return self._bind(WikiToolName.GET_PAGE_CHILDREN.value, PageInput, invoke)

    def _list_spaces(self) -> SkillDescriptor:
        """List the spaces the user may read."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            del payload
            spaces = await self._search_skill.list_spaces(user)
            return WikiSpacesResult(spaces=spaces)

        return self._bind(WikiToolName.LIST_SPACES.value, NoInput, invoke)

    def _get_comments(self) -> SkillDescriptor:
        """Retrieve the discussion of a page."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = PageInput.model_validate(payload.model_dump())
            comments = await self._search_skill.get_comments(arguments.page_id, user)
            return WikiCommentsResult(page_id=arguments.page_id, comments=comments)

        return self._bind(WikiToolName.GET_COMMENTS.value, PageInput, invoke)

    def _get_history(self) -> SkillDescriptor:
        """Retrieve the revision history of a page."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = PageInput.model_validate(payload.model_dump())
            return await self._search_skill.get_history(arguments.page_id, user)

        return self._bind(WikiToolName.GET_PAGE_HISTORY.value, PageInput, invoke)

    def _summarise(self) -> SkillDescriptor:
        """Summarise a page, optionally with its discussion or its children."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = SummarisePageInput.model_validate(payload.model_dump())
            if arguments.include_children:
                return await self._summary_skill.summarise_subtree(arguments.page_id, user)
            if arguments.include_comments:
                return await self._summary_skill.summarise_page_with_discussion(arguments.page_id, user)
            return await self._summary_skill.summarise_page(arguments.page_id, user)

        return self._bind(SUMMARISE_PAGE, SummarisePageInput, invoke)

    def _answer(self) -> SkillDescriptor:
        """Answer a question from the documentation."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = AnswerFromWikiInput.model_validate(payload.model_dump())
            return await self._answer_skill.answer(
                arguments.question,
                user,
                space_keys=arguments.space_keys,
            )

        return self._bind(ANSWER_FROM_WIKI, AnswerFromWikiInput, invoke)

    def _assess_freshness(self) -> SkillDescriptor:
        """Report how current a set of pages is."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = AssessFreshnessInput.model_validate(payload.model_dump())
            if arguments.page_ids:
                return await self._freshness_skill.assess_pages(arguments.page_ids, user)
            request = WikiSearchRequest(
                space_keys=(arguments.space_key,) if arguments.space_key else (),
                limit=50,
            )
            return await self._freshness_skill.assess_search(request, user)

        return self._bind(ASSESS_PAGE_FRESHNESS, AssessFreshnessInput, invoke)
