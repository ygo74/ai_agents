"""State-changing capabilities exposed by the Wiki Agent.

Every capability here goes through the confirmation broker before it reaches a
skill, and every skill re-checks the policy itself. Two independent guards, so
neither a change of orchestration nor a change of framework can weaken the rule.

The capability layer holds no business logic. What it does hold is the resolution
of a draft reference into the content that will actually be written, and that is
deliberately here rather than in the skill: it is the step that makes the text a
user approved the text the wiki receives.
"""

from __future__ import annotations

from pydantic import BaseModel

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.registry import SkillDescriptor, SkillInvocation
from ai_agent_lab.core.security.broker import ConfirmationBroker
from ai_agent_lab.core.security.confirmation import ConfirmationDecision, ConfirmationRequest
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.capabilities.results import (
    WikiCommentPostedResult,
    WikiPageDeletedResult,
    WikiPageDraftedResult,
    WikiPageWrittenResult,
)
from ai_agent_lab.wiki.capabilities.tool_inputs import (
    AddCommentInput,
    DraftPageContentInput,
    PageDraftInput,
    PageInput,
)
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.models import WikiPage, WikiPageDraft
from ai_agent_lab.wiki.domain.ports import WikiDraftStore
from ai_agent_lab.wiki.skills.authoring_skill import PageAuthoringSkill
from ai_agent_lab.wiki.skills.comment_skill import PageCommentSkill
from ai_agent_lab.wiki.skills.drafting_skill import PageDraftingSkill

DRAFT_PAGE_CONTENT = "draft_page_content"

# Every write capability this agent can offer, whatever a binding declares.
ALL_WRITE_CAPABILITIES = (
    DRAFT_PAGE_CONTENT,
    WikiToolName.CREATE_PAGE.value,
    WikiToolName.UPDATE_PAGE.value,
    WikiToolName.ADD_COMMENT.value,
    WikiToolName.DELETE_PAGE.value,
)

# Which MCP capability each write capability cannot work without.
#
# Drafting writes nothing, but it reads: revising a page means retrieving it
# first, so a server that cannot return a page cannot support drafting either.
# The two page writes need the drafting step, but that is a capability of this
# agent rather than of the server, so it is not expressed here.
REQUIRED_WRITE_MCP_CAPABILITY = {
    DRAFT_PAGE_CONTENT: (WikiToolName.GET_PAGE,),
    WikiToolName.CREATE_PAGE.value: (WikiToolName.CREATE_PAGE,),
    WikiToolName.UPDATE_PAGE.value: (WikiToolName.UPDATE_PAGE, WikiToolName.GET_PAGE),
    WikiToolName.ADD_COMMENT.value: (WikiToolName.ADD_COMMENT,),
    WikiToolName.DELETE_PAGE.value: (WikiToolName.DELETE_PAGE,),
}


class WikiWriteCapabilities:
    """Builds the descriptors of the capabilities that change the wiki."""

    def __init__(
        self,
        manifest: AgentManifest,
        drafting_skill: PageDraftingSkill,
        authoring_skill: PageAuthoringSkill,
        comment_skill: PageCommentSkill,
        draft_store: WikiDraftStore,
        broker: ConfirmationBroker,
    ) -> None:
        self._manifest = manifest
        self._drafting_skill = drafting_skill
        self._authoring_skill = authoring_skill
        self._comment_skill = comment_skill
        self._draft_store = draft_store
        self._broker = broker

    def descriptors(self) -> tuple[SkillDescriptor, ...]:
        """Every write capability the manifest declares, in its order."""
        builders = {
            DRAFT_PAGE_CONTENT: self._draft_page_content,
            WikiToolName.CREATE_PAGE.value: self._create_page,
            WikiToolName.UPDATE_PAGE.value: self._update_page,
            WikiToolName.ADD_COMMENT.value: self._add_comment,
            WikiToolName.DELETE_PAGE.value: self._delete_page,
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

    def _draft_page_content(self) -> SkillDescriptor:
        """Compose page content without writing anything."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = DraftPageContentInput.model_validate(payload.model_dump())
            draft = await self._compose(arguments, user)
            reference = self._draft_store.put(draft, user)
            return WikiPageDraftedResult(
                draft_reference=reference,
                space_key=draft.space_key,
                title="" if draft.title is None else draft.title.expose(),
                body=draft.body.expose(),
                page_id=draft.page_id,
                expected_version=draft.expected_version,
            )

        return self._bind(DRAFT_PAGE_CONTENT, DraftPageContentInput, invoke)

    def _create_page(self) -> SkillDescriptor:
        """Publish a prepared draft as a new page."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            reference = PageDraftInput.model_validate(payload.model_dump()).draft_reference
            draft = self._draft_store.get(reference, user)
            request, decision = await self._broker.resolve(
                required=self._authoring_skill.requires_confirmation(WikiToolName.CREATE_PAGE, user),
                build_request=lambda: self._authoring_skill.build_create_confirmation_request(
                    draft, user, target=reference
                ),
                user=user,
            )
            page = await self._authoring_skill.create_page(
                draft, user, request=request, decision=decision
            )
            return self._written(page)

        return self._bind(WikiToolName.CREATE_PAGE.value, PageDraftInput, invoke)

    def _update_page(self) -> SkillDescriptor:
        """Replace the body of a page with a prepared draft."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            reference = PageDraftInput.model_validate(payload.model_dump()).draft_reference
            draft = self._draft_store.get(reference, user)
            request, decision = await self._broker.resolve(
                required=self._authoring_skill.requires_confirmation(WikiToolName.UPDATE_PAGE, user),
                build_request=lambda: self._authoring_skill.build_update_confirmation_request(
                    draft, user, target=reference
                ),
                user=user,
            )
            page = await self._authoring_skill.update_page(
                draft, user, request=request, decision=decision
            )
            return self._written(page)

        return self._bind(WikiToolName.UPDATE_PAGE.value, PageDraftInput, invoke)

    def _add_comment(self) -> SkillDescriptor:
        """Post a comment on a page."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            arguments = AddCommentInput.model_validate(payload.model_dump())
            parent = arguments.parent_comment_id.strip() or None
            request, decision = await self._broker.resolve(
                required=self._comment_skill.requires_confirmation(user),
                build_request=lambda: self._comment_skill.build_confirmation_request(
                    arguments.page_id, arguments.body, user, parent_comment_id=parent
                ),
                user=user,
            )
            comment = await self._comment_skill.add_comment(
                arguments.page_id,
                arguments.body,
                user,
                parent_comment_id=parent,
                request=request,
                decision=decision,
            )
            return WikiCommentPostedResult(comment_id=comment.comment_id, page_id=comment.page_id)

        return self._bind(WikiToolName.ADD_COMMENT.value, AddCommentInput, invoke)

    def _delete_page(self) -> SkillDescriptor:
        """Remove a page from the wiki."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            page_id = PageInput.model_validate(payload.model_dump()).page_id
            request, decision = await self._delete_confirmation(page_id, user)
            await self._authoring_skill.delete_page(page_id, user, request=request, decision=decision)
            return WikiPageDeletedResult(page_id=page_id)

        return self._bind(WikiToolName.DELETE_PAGE.value, PageInput, invoke)

    async def _delete_confirmation(
        self,
        page_id: str,
        user: UserContext,
    ) -> tuple[ConfirmationRequest | None, ConfirmationDecision | None]:
        """Resolve the approval of a deletion.

        Built here rather than through a plain broker call because describing a
        deletion means reading the page first, to show a title instead of an
        opaque identifier. A confirmation nobody can recognise is one people
        click through, which would defeat the point of asking.

        The page is read only when an approval is actually required, so an
        ungated deployment pays nothing for it.
        """
        if not self._authoring_skill.requires_confirmation(WikiToolName.DELETE_PAGE, user):
            return None, None
        prepared = await self._authoring_skill.build_delete_confirmation_request(page_id, user)
        return await self._broker.resolve(required=True, build_request=lambda: prepared, user=user)

    async def _compose(self, arguments: DraftPageContentInput, user: UserContext) -> WikiPageDraft:
        """Draft either a revision of a page or a page that does not exist yet."""
        page_id = arguments.page_id.strip()
        if page_id:
            return await self._drafting_skill.draft_page_revision(page_id, arguments.instruction, user)
        return await self._drafting_skill.draft_new_page(
            arguments.space_key.strip(),
            arguments.title.strip(),
            arguments.instruction,
            user,
            source_page_ids=arguments.source_page_ids,
            parent_id=arguments.parent_id.strip() or None,
        )

    @staticmethod
    def _written(page: WikiPage) -> WikiPageWrittenResult:
        """Project a stored page onto the result the model receives."""
        return WikiPageWrittenResult(
            page_id=page.page_id,
            space_key=page.space_key,
            title=page.title.expose(),
            version=page.version,
            url=page.url,
        )
