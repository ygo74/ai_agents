"""State-changing capabilities exposed by the Mail Agent.

Every capability here goes through the confirmation broker before it reaches a
skill, and every skill re-checks the policy itself. Two independent guards, so
neither a change of orchestration nor a change of framework can weaken the rule.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.registry import SkillDescriptor
from ai_agent_lab.core.security.confirmation import ConfirmationDecision, ConfirmationRequest
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.capabilities.confirmation_broker import ConfirmationBroker
from ai_agent_lab.mail.capabilities.results import (
    DraftPreparedResult,
    LabelOperationAcknowledged,
    MailSentResult,
    OperationAcknowledged,
)
from ai_agent_lab.mail.capabilities.tool_inputs import (
    CreateLabelInput,
    DeleteLabelInput,
    DraftReferenceInput,
    DraftReplyInput,
    LabelInput,
    MessageInput,
    SetReadStateInput,
)
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.domain.models import MailDraft
from ai_agent_lab.mail.domain.ports import DraftStore
from ai_agent_lab.mail.skills.errors import EmptyMailSelectionError
from ai_agent_lab.mail.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.skills.reply_skill import MailReplySkill
from ai_agent_lab.mail.skills.send_skill import SendMailSkill

DRAFT_MAIL_REPLY = "draft_mail_reply"

GatedCall = Callable[[ConfirmationRequest | None, ConfirmationDecision | None], Awaitable[None]]


def housekeeping_target(message_id: str, label_id: str | None) -> str:
    """Identify the object a housekeeping confirmation is about.

    The presenter and the capability must name the same target, otherwise the
    answer collected from the user could not be matched to the operation it was
    given for.
    """
    return message_id if label_id is None else f"{message_id}:{label_id}"


class MailWriteCapabilities:
    """Builds the descriptors of the capabilities that change something."""

    def __init__(
        self,
        manifest: AgentManifest,
        reply_skill: MailReplySkill,
        send_skill: SendMailSkill,
        management_skill: MailManagementSkill,
        draft_store: DraftStore,
        broker: ConfirmationBroker,
    ) -> None:
        self._manifest = manifest
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
            self._create_label(),
            self._delete_label(),
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

        return self._bind(DRAFT_MAIL_REPLY, DraftReplyInput, invoke)

    def _send_draft(self) -> SkillDescriptor:
        """Deliver a previously prepared draft."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            reference = DraftReferenceInput.model_validate(payload).draft_reference
            draft = self._draft_store.get(reference, user)
            request, decision = await self._broker.resolve(
                required=self._send_skill.requires_confirmation(user),
                build_request=lambda: self._send_skill.build_confirmation_request(draft, user, target=reference),
                user=user,
            )
            result = await self._send_skill.send(draft, user, request=request, decision=decision)
            return MailSentResult(
                message_id=result.message_id,
                thread_id=result.thread_id,
                sent_at=result.sent_at.isoformat(),
            )

        return self._bind(MailToolName.SEND_MAIL.value, DraftReferenceInput, invoke)

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

    def _create_label(self) -> SkillDescriptor:
        """Make a label exist in the mailbox."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            name = CreateLabelInput.model_validate(payload).name
            outcome = await self._run_label_change(
                tool=MailToolName.CREATE_LABEL,
                label=name,
                user=user,
                run=lambda request, decision: self._management_skill.create_label(
                    name, user, request=request, decision=decision
                ),
            )
            return LabelOperationAcknowledged(
                tool_name=MailToolName.CREATE_LABEL.value,
                label_id=outcome.label.label_id,
                label_name=outcome.label.name.expose(),
                detail="created" if outcome.created else "already existed, nothing was created",
            )

        return self._housekeeping_descriptor(MailToolName.CREATE_LABEL, CreateLabelInput, invoke)

    def _delete_label(self) -> SkillDescriptor:
        """Delete a label from the mailbox."""

        async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
            label_id = DeleteLabelInput.model_validate(payload).label_id
            await self._run_label_change(
                tool=MailToolName.DELETE_LABEL,
                label=label_id,
                user=user,
                run=lambda request, decision: self._management_skill.delete_label(
                    label_id, user, request=request, decision=decision
                ),
            )
            return LabelOperationAcknowledged(
                tool_name=MailToolName.DELETE_LABEL.value,
                label_id=label_id,
                label_name="",
                detail="deleted, and detached from every message that carried it",
            )

        return self._housekeeping_descriptor(MailToolName.DELETE_LABEL, DeleteLabelInput, invoke)

    def _bind(
        self,
        tool_name: str,
        input_model: type[BaseModel],
        invoke: Callable[[BaseModel, UserContext], Awaitable[BaseModel]],
    ) -> SkillDescriptor:
        """Bind a delivered manifest to the code running the capability."""
        return SkillDescriptor.from_manifest(self._manifest.skill(tool_name), input_model, invoke)

    def _housekeeping_descriptor(
        self,
        tool: MailToolName,
        input_model: type[BaseModel],
        invoke: Callable[[BaseModel, UserContext], Awaitable[BaseModel]],
    ) -> SkillDescriptor:
        """Assemble the descriptor of a housekeeping capability."""
        return self._bind(tool.value, input_model, invoke)

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
            build_request=lambda: self._management_skill.build_confirmation_request(
                tool,
                message_id,
                user,
                label_id=label_id,
                is_read=is_read,
                target=housekeeping_target(message_id, label_id),
            ),
            user=user,
        )
        await run(request, decision)
        return OperationAcknowledged(tool_name=tool.value, message_id=message_id, detail=detail)

    async def _run_label_change[ResultT](
        self,
        *,
        tool: MailToolName,
        label: str,
        user: UserContext,
        run: Callable[[ConfirmationRequest | None, ConfirmationDecision | None], Awaitable[ResultT]],
    ) -> ResultT:
        """Confirm if needed, then change which labels the mailbox has.

        The confirmation names the label rather than a message, so the answer
        the user gives can be matched to the operation it was asked for.
        """
        request, decision = await self._broker.resolve(
            required=self._management_skill.requires_confirmation(tool, user),
            build_request=lambda: self._management_skill.build_label_confirmation_request(tool, label, user),
            user=user,
        )
        return await run(request, decision)

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
