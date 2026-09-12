"""Search and retrieval skills.

These skills carry no language-model reasoning: turning a structured request
into a mailbox query and ordering the outcome is deterministic work, so it is
implemented in code rather than delegated to a model.
"""

from __future__ import annotations

import logging

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.models import (
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailThread,
)
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.tools_port import MailReadTools

_logger = logging.getLogger(__name__)


class MailSearchSkill:
    """Finds messages matching a structured request.

    Every search variation - by sender, recipient, subject, keyword, label, date
    range, unread state, or any combination - is expressed by the request, so a
    single MCP search capability is enough.
    """

    def __init__(self, mail_tools: MailReadTools) -> None:
        _logger.info("Initializing Mail search skill")
        _logger.debug(
            "MailSearchSkill.__init__ arguments: mail_tools_type=%s",
            type(mail_tools).__name__,
        )
        self._mail_tools = mail_tools

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        """Return the headers matching the request."""
        _logger.info("Searching mailbox")
        _logger.debug(
            "MailSearchSkill.search arguments: request_type=%s, limit=%d, unread_only=%s, user_id=%s",
            type(request).__name__,
            request.limit,
            request.unread_only,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        return await self._mail_tools.search(request, user)

    async def search_unread(self, user: UserContext, *, limit: int = 20) -> MailSearchResult:
        """Return the unread messages of the mailbox."""
        _logger.info("Searching unread mailbox messages")
        _logger.debug(
            "MailSearchSkill.search_unread arguments: user_id=%s, limit=%d",
            user.user_id,
            limit,
        )
        return await self.search(MailSearchRequest(unread_only=True, limit=limit), user)


class MailReadSkill:
    """Retrieves a single message or a whole conversation."""

    def __init__(self, mail_tools: MailReadTools) -> None:
        _logger.info("Initializing Mail read skill")
        _logger.debug(
            "MailReadSkill.__init__ arguments: mail_tools_type=%s",
            type(mail_tools).__name__,
        )
        self._mail_tools = mail_tools

    async def read_message(self, message_id: str, user: UserContext) -> MailMessage:
        """Return one complete message."""
        _logger.info("Reading mailbox message")
        _logger.debug(
            "MailReadSkill.read_message arguments: message_id=%s, user_id=%s",
            message_id,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        return await self._mail_tools.get_message(message_id, user)

    async def read_thread(self, thread_id: str, user: UserContext) -> MailThread:
        """Return a whole conversation, oldest message first."""
        _logger.info("Reading mailbox thread")
        _logger.debug(
            "MailReadSkill.read_thread arguments: thread_id=%s, user_id=%s",
            thread_id,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return thread.model_copy(update={"messages": thread.in_chronological_order()})

    async def read_messages(self, message_ids: tuple[str, ...], user: UserContext) -> tuple[MailMessage, ...]:
        """Return several messages, preserving the requested order."""
        _logger.info("Reading mailbox message loop")
        _logger.debug(
            "MailReadSkill.read_messages arguments: message_ids=%s, count=%d, user_id=%s",
            message_ids,
            len(message_ids),
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        return tuple([await self._mail_tools.get_message(message_id, user) for message_id in message_ids])
