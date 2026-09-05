"""Read-only capabilities exposed by the Mail Agent."""

from __future__ import annotations

from pydantic import BaseModel

from ai_agent_lab.agents.definition import SkillDescriptor
from ai_agent_lab.agents.mail.converters import MailSearchRequestFactory
from ai_agent_lab.agents.mail.results import (
    MailActionsResult,
    MailClassificationsResult,
    MailLabelsResult,
)
from ai_agent_lab.agents.mail.tool_inputs import (
    ClassifyMailInput,
    ExtractActionsInput,
    MessageInput,
    MessageOrThreadInput,
    NoInput,
    SearchMailInput,
    ThreadInput,
)
from ai_agent_lab.domain.mail.models import MailAction
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.domain.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.mcp.mail.catalog import MailToolCatalog, MailToolName
from ai_agent_lab.skills.mail.action_extraction_skill import MailActionExtractionSkill
from ai_agent_lab.skills.mail.classification_skill import MailClassificationSkill
from ai_agent_lab.skills.mail.errors import EmptyMailSelectionError
from ai_agent_lab.skills.mail.management_skill import MailManagementSkill
from ai_agent_lab.skills.mail.search_skill import MailReadSkill, MailSearchSkill
from ai_agent_lab.skills.mail.summary_skill import MailSummarySkill

SUMMARISE_MAIL = "summarise_mail"
CLASSIFY_MAIL = "classify_mail"
EXTRACT_MAIL_ACTIONS = "extract_mail_actions"


def _analysis_operation(tool_name: str) -> ToolOperationDescriptor:
    """Describe a capability that only reads and reasons."""
    return ToolOperationDescriptor(
        tool_name=tool_name,
        operation_type=OperationType.READ,
        risk_level=RiskLevel.LOW,
        required_permission=Permission.MAIL_READ,
        confirmation_required_by_default=False,
    )


class MailReadCapabilities:
    """Builds the descriptors of the capabilities that never change anything."""

    def __init__(
        self,
        catalog: MailToolCatalog,
        search_skill: MailSearchSkill,
        read_skill: MailReadSkill,
        summary_skill: MailSummarySkill,
        classification_skill: MailClassificationSkill,
        action_skill: MailActionExtractionSkill,
        management_skill: MailManagementSkill,
        search_request_factory: MailSearchRequestFactory,
    ) -> None:
        self._catalog = catalog
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

    def _list_labels(self) -> SkillDescriptor:
        """List the labels available in the mailbox.

        Applying or removing a label needs an identifier, so the model must be
        able to discover them instead of guessing.
        """

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            NoInput.model_validate(payload)
            return MailLabelsResult(labels=await self._management_skill.list_labels(user))

        return SkillDescriptor(
            tool_name=MailToolName.LIST_LABELS.value,
            description=self._catalog.description(MailToolName.LIST_LABELS),
            input_model=NoInput,
            operation=self._catalog.descriptor(MailToolName.LIST_LABELS),
            invoke=invoke,
        )

    def _search(self) -> SkillDescriptor:
        """Search the mailbox."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            request = self._search_request_factory.build(SearchMailInput.model_validate(payload))
            return await self._search_skill.search(request, user)

        return SkillDescriptor(
            tool_name=MailToolName.SEARCH_MAIL.value,
            description=self._catalog.description(MailToolName.SEARCH_MAIL),
            input_model=SearchMailInput,
            operation=self._catalog.descriptor(MailToolName.SEARCH_MAIL),
            invoke=invoke,
        )

    def _read_message(self) -> SkillDescriptor:
        """Retrieve one complete message."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            return await self._read_skill.read_message(MessageInput.model_validate(payload).message_id, user)

        return SkillDescriptor(
            tool_name=MailToolName.GET_MAIL.value,
            description=self._catalog.description(MailToolName.GET_MAIL),
            input_model=MessageInput,
            operation=self._catalog.descriptor(MailToolName.GET_MAIL),
            invoke=invoke,
        )

    def _read_thread(self) -> SkillDescriptor:
        """Retrieve a whole conversation."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            return await self._read_skill.read_thread(ThreadInput.model_validate(payload).thread_id, user)

        return SkillDescriptor(
            tool_name=MailToolName.GET_THREAD.value,
            description=self._catalog.description(MailToolName.GET_THREAD),
            input_model=ThreadInput,
            operation=self._catalog.descriptor(MailToolName.GET_THREAD),
            invoke=invoke,
        )

    def _summarise(self) -> SkillDescriptor:
        """Summarise a message or a conversation."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = MessageOrThreadInput.model_validate(payload)
            if selection.thread_id:
                return await self._summary_skill.summarise_thread(selection.thread_id, user)
            if selection.message_id:
                return await self._summary_skill.summarise_message(selection.message_id, user)
            raise EmptyMailSelectionError(SUMMARISE_MAIL)

        return SkillDescriptor(
            tool_name=SUMMARISE_MAIL,
            description=(
                "Summarise a message or a whole conversation. Returns the summary, the key points, "
                "the decisions, the actions expected from the owner, the deadlines, the participants, "
                "the open questions and the source message identifiers. Has no side effect."
            ),
            input_model=MessageOrThreadInput,
            operation=_analysis_operation(SUMMARISE_MAIL),
            invoke=invoke,
        )

    def _classify(self) -> SkillDescriptor:
        """Assign a category to messages."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = ClassifyMailInput.model_validate(payload)
            classifications = await self._classification_skill.classify_messages(tuple(selection.message_ids), user)
            return MailClassificationsResult(classifications=classifications)

        return SkillDescriptor(
            tool_name=CLASSIFY_MAIL,
            description=(
                "Assign one business category to each of the given messages, with a confidence and a "
                "short reason. Has no side effect and does not apply any label to the mailbox."
            ),
            input_model=ClassifyMailInput,
            operation=_analysis_operation(CLASSIFY_MAIL),
            invoke=invoke,
        )

    def _extract_actions(self) -> SkillDescriptor:
        """List the actions expected from the mailbox owner."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = ExtractActionsInput.model_validate(payload)
            actions = await self._actions_for(selection, user)
            if selection.explicit_only:
                actions = MailActionExtractionSkill.only_explicit(actions)
            return MailActionsResult(actions=actions)

        return SkillDescriptor(
            tool_name=EXTRACT_MAIL_ACTIONS,
            description=(
                "List the actions the mailbox owner is expected to perform, based on the given messages "
                "or conversation. Each action states whether it was explicitly requested or deduced, its "
                "confidence, its due date when one is given, and its source message. Has no side effect."
            ),
            input_model=ExtractActionsInput,
            operation=_analysis_operation(EXTRACT_MAIL_ACTIONS),
            invoke=invoke,
        )

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
