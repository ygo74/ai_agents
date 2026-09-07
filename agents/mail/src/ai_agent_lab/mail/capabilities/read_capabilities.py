"""Read-only capabilities exposed by the Mail Agent."""

from __future__ import annotations

from pydantic import BaseModel

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.registry import SkillDescriptor, SkillInvocation
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.capabilities.converters import MailSearchRequestFactory
from ai_agent_lab.mail.capabilities.results import (
    MailActionsResult,
    MailClassificationsResult,
    MailLabelsResult,
)
from ai_agent_lab.mail.capabilities.tool_inputs import (
    ClassifyMailInput,
    ExtractActionsInput,
    MessageInput,
    MessageOrThreadInput,
    NoInput,
    SearchMailInput,
    ThreadInput,
)
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.domain.models import MailAction
from ai_agent_lab.mail.skills.action_extraction_skill import MailActionExtractionSkill
from ai_agent_lab.mail.skills.classification_skill import MailClassificationSkill
from ai_agent_lab.mail.skills.errors import EmptyMailSelectionError
from ai_agent_lab.mail.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.skills.search_skill import MailReadSkill, MailSearchSkill
from ai_agent_lab.mail.skills.summary_skill import MailSummarySkill

SUMMARISE_MAIL = "summarise_mail"
CLASSIFY_MAIL = "classify_mail"
EXTRACT_MAIL_ACTIONS = "extract_mail_actions"


class MailReadCapabilities:
    """Builds the descriptors of the capabilities that never change anything."""

    def __init__(
        self,
        manifest: AgentManifest,
        search_skill: MailSearchSkill,
        read_skill: MailReadSkill,
        summary_skill: MailSummarySkill,
        classification_skill: MailClassificationSkill,
        action_skill: MailActionExtractionSkill,
        management_skill: MailManagementSkill,
        search_request_factory: MailSearchRequestFactory,
    ) -> None:
        self._manifest = manifest
        self._search_skill = search_skill
        self._read_skill = read_skill
        self._summary_skill = summary_skill
        self._classification_skill = classification_skill
        self._action_skill = action_skill
        self._management_skill = management_skill
        self._search_request_factory = search_request_factory

    def descriptors(self) -> tuple[SkillDescriptor, ...]:
        """Every read-only capability of the Mail Agent."""
        return (
            self._search(),
            self._read_message(),
            self._read_thread(),
            self._list_labels(),
            self._summarise(),
            self._classify(),
            self._extract_actions(),
        )

    def _bind(
        self,
        tool_name: str,
        input_model: type[BaseModel],
        invoke: SkillInvocation,
    ) -> SkillDescriptor:
        """Bind a delivered manifest to the code running the capability."""
        return SkillDescriptor.from_manifest(self._manifest.skill(tool_name), input_model, invoke)

    def _list_labels(self) -> SkillDescriptor:
        """List the labels available in the mailbox.

        Applying or removing a label needs an identifier, so the model must be
        able to discover them instead of guessing.
        """

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            NoInput.model_validate(payload)
            return MailLabelsResult(labels=await self._management_skill.list_labels(user))

        return self._bind(MailToolName.LIST_LABELS.value, NoInput, invoke)

    def _search(self) -> SkillDescriptor:
        """Search the mailbox."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            request = self._search_request_factory.build(SearchMailInput.model_validate(payload))
            return await self._search_skill.search(request, user)

        return self._bind(MailToolName.SEARCH_MAIL.value, SearchMailInput, invoke)

    def _read_message(self) -> SkillDescriptor:
        """Retrieve one complete message."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            return await self._read_skill.read_message(MessageInput.model_validate(payload).message_id, user)

        return self._bind(MailToolName.GET_MAIL.value, MessageInput, invoke)

    def _read_thread(self) -> SkillDescriptor:
        """Retrieve a whole conversation."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            return await self._read_skill.read_thread(ThreadInput.model_validate(payload).thread_id, user)

        return self._bind(MailToolName.GET_THREAD.value, ThreadInput, invoke)

    def _summarise(self) -> SkillDescriptor:
        """Summarise a message or a conversation."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = MessageOrThreadInput.model_validate(payload)
            if selection.thread_id:
                return await self._summary_skill.summarise_thread(selection.thread_id, user)
            if selection.message_id:
                return await self._summary_skill.summarise_message(selection.message_id, user)
            raise EmptyMailSelectionError(SUMMARISE_MAIL)

        return self._bind(SUMMARISE_MAIL, MessageOrThreadInput, invoke)

    def _classify(self) -> SkillDescriptor:
        """Assign a category to messages."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = ClassifyMailInput.model_validate(payload)
            classifications = await self._classification_skill.classify_messages(tuple(selection.message_ids), user)
            return MailClassificationsResult(classifications=classifications)

        return self._bind(CLASSIFY_MAIL, ClassifyMailInput, invoke)

    def _extract_actions(self) -> SkillDescriptor:
        """List the actions expected from the mailbox owner."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = ExtractActionsInput.model_validate(payload)
            actions = await self._actions_for(selection, user)
            if selection.explicit_only:
                actions = MailActionExtractionSkill.only_explicit(actions)
            return MailActionsResult(actions=actions)

        return self._bind(EXTRACT_MAIL_ACTIONS, ExtractActionsInput, invoke)

    async def _actions_for(
        self,
        selection: ExtractActionsInput,
        user: UserContext,
    ) -> tuple[MailAction, ...]:
        """Run the extraction over whichever scope was requested."""
        if selection.thread_id:
            return await self._action_skill.extract_from_thread(selection.thread_id, user)
        if selection.message_ids:
            return await self._action_skill.extract_from_messages(tuple(selection.message_ids), user)
        raise EmptyMailSelectionError(EXTRACT_MAIL_ACTIONS)
