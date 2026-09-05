"""Search and retrieval skills.

These skills carry no language-model reasoning: turning a structured request
into a mailbox query and ordering the outcome is deterministic work, so it is
implemented in code rather than delegated to a model.
"""

from __future__ import annotations

from ai_agent_lab.domain.mail.models import (
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailThread,
)
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.mcp.mail.contracts import MailReadTools


class MailSearchSkill:
    """Finds messages matching a structured request.

    Every search variation - by sender, recipient, subject, keyword, label, date
    range, unread state, or any combination - is expressed by the request, so a
    single MCP search capability is enough.
    """

    def __init__(self, mail_tools: MailReadTools) -> None:
        self._mail_tools = mail_tools

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the headers matching the request."""
        user.require_permission(Permission.MAIL_READ)
        return await self._mail_tools.search(request, user)

    async def search_unread(self, user: UserContext, *, limit: int = 20) -> MailSearchResult:
        """Return the unread messages of the mailbox."""
        return await self.search(MailSearchRequest(unread_only=True, limit=limit), user)


class MailReadSkill:
    """Retrieves a single message or a whole conversation."""

    def __init__(self, mail_tools: MailReadTools) -> None:
        self._mail_tools = mail_tools

    async def read_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        user.require_permission(Permission.MAIL_READ)
        return await self._mail_tools.get_message(message_id, user)

    async def read_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a whole conversation, oldest message first."""
        user.require_permission(Permission.MAIL_READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return thread.model_copy(update={"messages": thread.in_chronological_order()})

    async def read_messages(self, message_ids: tuple[str, ...], user: UserContext) -> tuple[MailMessage, ...]:
        """Return several messages, preserving the requested order."""
        user.require_permission(Permission.MAIL_READ)
        return tuple([await self._mail_tools.get_message(message_id, user) for message_id in message_ids])
