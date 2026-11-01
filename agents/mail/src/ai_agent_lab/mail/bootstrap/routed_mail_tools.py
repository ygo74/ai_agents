"""Route grouped domain operations to their individual manifest skills."""

from __future__ import annotations

from collections.abc import Callable

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.application.ports.mail_tools import MailTools
from ai_agent_lab.mail.domain.models import (
    MailDraft,
    MailLabel,
    MailLabelOutcome,
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailSendRequest,
    MailSendResult,
    MailThread,
)
from ai_agent_lab.mail.domain.operation_names import MailToolName


class RoutedMailTools:
    """Route grouped operations by name; a fixed resolver keeps reasoning reads on one skill."""

    def __init__(self, tools_for: Callable[[str], MailTools]) -> None:
        self._tools_for = tools_for

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        return await self._tools_for(MailToolName.SEARCH_MAIL).search(request, user)

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        return await self._tools_for(MailToolName.GET_MAIL).get_message(message_id, user)

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        return await self._tools_for(MailToolName.GET_THREAD).get_thread(thread_id, user)

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        return await self._tools_for(MailToolName.LIST_LABELS).list_labels(user)

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        return await self._tools_for(MailToolName.CREATE_DRAFT).create_draft(draft, user)

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        return await self._tools_for(MailToolName.SEND_MAIL).send(request, user)

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        await self._tools_for(MailToolName.MARK_READ).set_read_state(message_id, is_read, user)

    async def archive(self, message_id: str, user: UserContext) -> None:
        await self._tools_for(MailToolName.ARCHIVE_MAIL).archive(message_id, user)

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        await self._tools_for(MailToolName.APPLY_LABEL).apply_label(message_id, label_id, user)

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        await self._tools_for(MailToolName.REMOVE_LABEL).remove_label(message_id, label_id, user)

    async def create_label(self, name: str, user: UserContext) -> MailLabelOutcome:
        return await self._tools_for(MailToolName.CREATE_LABEL).create_label(name, user)

    async def delete_label(self, label_id: str, user: UserContext) -> None:
        await self._tools_for(MailToolName.DELETE_LABEL).delete_label(label_id, user)
