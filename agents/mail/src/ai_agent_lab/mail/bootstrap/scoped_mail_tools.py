"""Per-skill alias-scoped view over one server's shared mail tools object.

Two sibling skills on the same server share one connection and one underlying
dialect object (so the connection pool and any dialect-internal state stay
single), but each skill's manifest declares its own subset of
:class:`MailToolName` aliases. Handing the raw shared object to every skill
would silently let a read-only skill invoke writes the server supports but the
skill's own manifest never declared. This wrapper is what
:meth:`MailToolsProvider.build_for_skill` actually returns: it forwards each
domain-port call to the shared object only if the skill's own alias set
allows it, and raises an explicit domain error otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ygo74.agent_runtime.domains.mcp.registry import McpSkillServerView
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.application.ports.mail_tools import MailTools
from ai_agent_lab.mail.domain.operation_names import MailToolName
from ai_agent_lab.mail.infrastructure.mcp.errors import McpBindingError

if TYPE_CHECKING:
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

class ScopedMailTools:
    """Restrict a shared :class:`MailTools` object to one skill's own aliases.

    Args:
        tool_name: Manifest identity of the skill this scope belongs to.
        delegate: The shared, per-server dialect object every sibling skill routes through.
        view: Runtime alias scope and lifecycle of the selected connection.
    """

    def __init__(
        self,
        tool_name: str,
        delegate: MailTools,
        view: McpSkillServerView,
    ) -> None:
        self._tool_name = tool_name
        self._delegate = delegate
        self._view = view

    def _require(self, operation: MailToolName) -> None:
        """Reject a call to an operation this skill's manifest does not declare."""
        if operation.value not in self._view.tools:
            raise McpBindingError(
                f"skill {self._tool_name!r} does not declare MCP tool alias {operation.value!r}"
            )

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the message headers matching a structured query."""
        self._require(MailToolName.SEARCH_MAIL)
        return await self._delegate.search(request, user)

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        self._require(MailToolName.GET_MAIL)
        return await self._delegate.get_message(message_id, user)

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a full conversation."""
        self._require(MailToolName.GET_THREAD)
        return await self._delegate.get_thread(thread_id, user)

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        """Return the labels available in the mailbox."""
        self._require(MailToolName.LIST_LABELS)
        return await self._delegate.list_labels(user)

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        """Persist a draft without delivering anything."""
        self._require(MailToolName.CREATE_DRAFT)
        return await self._delegate.create_draft(draft, user)

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        """Deliver a draft to its recipients."""
        self._require(MailToolName.SEND_MAIL)
        return await self._delegate.send(request, user)

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        """Mark a message as read or unread."""
        self._require(MailToolName.MARK_READ)
        await self._delegate.set_read_state(message_id, is_read, user)

    async def archive(self, message_id: str, user: UserContext) -> None:
        """Remove a message from the inbox without deleting it."""
        self._require(MailToolName.ARCHIVE_MAIL)
        await self._delegate.archive(message_id, user)

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Attach a label or category to a message."""
        self._require(MailToolName.APPLY_LABEL)
        await self._delegate.apply_label(message_id, label_id, user)

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        """Detach a label or category from a message."""
        self._require(MailToolName.REMOVE_LABEL)
        await self._delegate.remove_label(message_id, label_id, user)

    async def create_label(self, name: str, user: UserContext) -> MailLabelOutcome:
        """Make a label exist, reporting whether it had to be created."""
        self._require(MailToolName.CREATE_LABEL)
        return await self._delegate.create_label(name, user)

    async def delete_label(self, label_id: str, user: UserContext) -> None:
        """Delete a label, detaching it from every message carrying it."""
        self._require(MailToolName.DELETE_LABEL)
        await self._delegate.delete_label(label_id, user)
