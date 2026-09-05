"""State-changing capabilities exposed by the Mail Agent.

Every capability here goes through the confirmation broker before it reaches a
skill, and every skill re-checks the policy itself. Two independent guards, so
neither a change of orchestration nor a change of framework can weaken the rule.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from ai_agent_lab.agents.definition import SkillDescriptor
from ai_agent_lab.agents.mail.confirmation_broker import ConfirmationBroker
from ai_agent_lab.agents.mail.results import (
    DraftPreparedResult,
    MailSentResult,
    OperationAcknowledged,
)
from ai_agent_lab.agents.mail.tool_inputs import (
    DraftReferenceInput,
    DraftReplyInput,
    LabelInput,
    MessageInput,
    SetReadStateInput,
)
from ai_agent_lab.domain.mail.models import MailDraft
from ai_agent_lab.domain.mail.ports import DraftStore
from ai_agent_lab.domain.security.confirmation import ConfirmationDecision, ConfirmationRequest
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.domain.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.mcp.mail.catalog import MailToolCatalog, MailToolName
from ai_agent_lab.skills.mail.errors import EmptyMailSelectionError
from ai_agent_lab.skills.mail.management_skill import MailManagementSkill
from ai_agent_lab.skills.mail.reply_skill import MailReplySkill
from ai_agent_lab.skills.mail.send_skill import SendMailSkill

DRAFT_MAIL_REPLY = "draft_mail_reply"

GatedCall = Callable[[ConfirmationRequest | None, ConfirmationDecision | None], Awaitable[None]]

_DRAFT_REPLY_OPERATION = ToolOperationDescriptor(
    tool_name=DRAFT_MAIL_REPLY,
    operation_type=OperationType.READ,
    risk_level=RiskLevel.LOW,
    required_permission=Permission.MAIL_DRAFT,
    confirmation_required_by_default=False,
)


class MailWriteCapabilities:
    """Builds the descriptors of the capabilities that change something."""

    def __init__(
        self,
        catalog: MailToolCatalog,
        reply_skill: MailReplySkill,
        send_skill: SendMailSkill,
        management_skill: MailManagementSkill,
        draft_store: DraftStore,
        broker: ConfirmationBroker,
    ) -> None:
        self._catalog = catalog
        self._reply_skill = reply_skill
        self._send_skill = send_skill
        self._management_skill = management_skill
        self._draft_store = draft_store
        self._broker = broker

    def descriptors(self) -> tuple[SkillDescriptor, ...]:
        """Every drafting and state-changing capability of the Mail Agent."""
        return (
            self._draft_reply(),
            self._send_draft(),
            self._set_read_state(),
            self._archive(),
            self._apply_label(),
            self._remove_label(),
        )

    def _draft_reply(self) -> SkillDescriptor:
        """Prepare a reply without sending or storing it."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = DraftReplyInput.model_validate(payload)
            draft = await self._compose(selection, user)
            reference = self._draft_store.put(draft, user)
            return DraftPreparedResult(
                draft_reference=reference,
                to=tuple(str(address) for address in draft.to),
                cc=tuple(str(address) for address in draft.cc),
                subject=draft.subject.expose(),
                body=draft.body.expose(),
                in_reply_to_message_id=draft.in_reply_to_message_id,
            )

        return SkillDescriptor(
            tool_name=DRAFT_MAIL_REPLY,
            description=(
                "Prepare a reply to a message, or to the most recent message of a conversation, following "
                "the intent stated by the mailbox owner. Returns the draft and a draft reference. Nothing "
                "is sent and nothing is stored in the mailbox."
            ),
            input_model=DraftReplyInput,
            operation=_DRAFT_REPLY_OPERATION,
            invoke=invoke,
        )

    def _send_draft(self) -> SkillDescriptor:
        """Deliver a previously prepared draft."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            reference = DraftReferenceInput.model_validate(payload).draft_reference
            draft = self._draft_store.get(reference, user)
            request, decision = await self._broker.resolve(
                required=self._send_skill.requires_confirmation(user),
                request=self._send_skill.build_confirmation_request(draft),
                user=user,
            )
            result = await self._send_skill.send(draft, user, request=request, decision=decision)
            return MailSentResult(
                message_id=result.message_id,
                thread_id=result.thread_id,
                sent_at=result.sent_at.isoformat(),
            )

        return SkillDescriptor(
            tool_name=MailToolName.SEND_MAIL.value,
            description=(
                "Send a reply prepared earlier, identified by its draft reference. The content delivered "
                "is exactly the content of that draft. This is irreversible and the mailbox owner is "
                "asked to approve it first."
            ),
            input_model=DraftReferenceInput,
            operation=self._catalog.descriptor(MailToolName.SEND_MAIL),
            invoke=invoke,
        )

    def _set_read_state(self) -> SkillDescriptor:
        """Mark a message as read or unread."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = SetReadStateInput.model_validate(payload)
            return await self._run_housekeeping(
                tool=MailToolName.MARK_READ,
                message_id=selection.message_id,
                user=user,
                is_read=selection.is_read,
                run=lambda request, decision: self._management_skill.set_read_state(
                    selection.message_id, selection.is_read, user, request=request, decision=decision
                ),
                detail="marked as read" if selection.is_read else "marked as unread",
            )

        return self._housekeeping_descriptor(MailToolName.MARK_READ, SetReadStateInput, invoke)

    def _archive(self) -> SkillDescriptor:
        """Remove a message from the inbox."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            message_id = MessageInput.model_validate(payload).message_id
            return await self._run_housekeeping(
                tool=MailToolName.ARCHIVE_MAIL,
                message_id=message_id,
                user=user,
                run=lambda request, decision: self._management_skill.archive(
                    message_id, user, request=request, decision=decision
                ),
                detail="archived",
            )

        return self._housekeeping_descriptor(MailToolName.ARCHIVE_MAIL, MessageInput, invoke)

    def _apply_label(self) -> SkillDescriptor:
        """Attach a label to a message."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = LabelInput.model_validate(payload)
            return await self._run_housekeeping(
                tool=MailToolName.APPLY_LABEL,
                message_id=selection.message_id,
                user=user,
                label_id=selection.label_id,
                run=lambda request, decision: self._management_skill.apply_label(
                    selection.message_id, selection.label_id, user, request=request, decision=decision
                ),
                detail=f"label {selection.label_id} applied",
            )

        return self._housekeeping_descriptor(MailToolName.APPLY_LABEL, LabelInput, invoke)

    def _remove_label(self) -> SkillDescriptor:
        """Detach a label from a message."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            selection = LabelInput.model_validate(payload)
            return await self._run_housekeeping(
                tool=MailToolName.REMOVE_LABEL,
                message_id=selection.message_id,
                user=user,
                label_id=selection.label_id,
                run=lambda request, decision: self._management_skill.remove_label(
                    selection.message_id, selection.label_id, user, request=request, decision=decision
                ),
                detail=f"label {selection.label_id} removed",
            )

        return self._housekeeping_descriptor(MailToolName.REMOVE_LABEL, LabelInput, invoke)

    def _housekeeping_descriptor(
        self,
        tool: MailToolName,
        input_model: type[BaseModel],
        invoke: Callable[[BaseModel, UserContext], Awaitable[BaseModel]],
    ) -> SkillDescriptor:
        """Assemble the descriptor of a housekeeping capability."""
        return SkillDescriptor(
            tool_name=tool.value,
            description=self._catalog.description(tool),
            input_model=input_model,
            operation=self._catalog.descriptor(tool),
            invoke=invoke,
        )

    async def _run_housekeeping(
        self,
        *,
        tool: MailToolName,
        message_id: str,
        user: UserContext,
        run: GatedCall,
        detail: str,
        label_id: str | None = None,
        is_read: bool | None = None,
    ) -> OperationAcknowledged:
        """Confirm if needed, run the operation, and acknowledge it."""
        request, decision = await self._broker.resolve(
            required=self._management_skill.requires_confirmation(tool, user),
            request=self._management_skill.build_confirmation_request(
                tool, message_id, label_id=label_id, is_read=is_read
            ),
            user=user,
        )
        await run(request, decision)
        return OperationAcknowledged(tool_name=tool.value, message_id=message_id, detail=detail)

    async def _compose(self, selection: DraftReplyInput, user: UserContext) -> MailDraft:
        """Draft a reply over whichever scope was requested."""
        if selection.thread_id:
            return await self._reply_skill.draft_reply_to_thread(
                selection.thread_id, selection.intent, user, reply_all=selection.reply_all
            )
        if selection.message_id:
            return await self._reply_skill.draft_reply_to_message(
                selection.message_id, selection.intent, user, reply_all=selection.reply_all
            )
        raise EmptyMailSelectionError(DRAFT_MAIL_REPLY)
