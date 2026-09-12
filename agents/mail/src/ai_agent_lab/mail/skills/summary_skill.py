"""Summarisation of a message, a thread or a set of related messages."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.models import MailMessage, MailSummary
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.skills.analysis import MailAnalysisMapper, MailSummaryOutput
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.skills.errors import EmptyMailSelectionError
from ai_agent_lab.mail.tools_port import MailReadTools

_logger = logging.getLogger(__name__)


class MailSummarySkill:
    """Produces a structured summary grounded in retrieved messages.

    Retrieval is delegated to the MCP layer and reasoning to the injected
    :class:`TextReasoner`, so the skill itself stays free of both transport and
    framework concerns. The reasoning instructions are injected too: they are
    delivered configuration, not code.
    """

    def __init__(
        self,
        mail_tools: MailReadTools,
        reasoner: TextReasoner,
        context_builder: MailContextBuilder,
        mapper: MailAnalysisMapper,
        instructions: str,
    ) -> None:
        _logger.info("Initializing Mail summary skill")
        _logger.debug(
            "MailSummarySkill.__init__ arguments: mail_tools_type=%s, reasoner_type=%s, "
            "context_builder_type=%s, mapper_type=%s, instructions_length=%d",
            type(mail_tools).__name__,
            type(reasoner).__name__,
            type(context_builder).__name__,
            type(mapper).__name__,
            len(instructions),
        )
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._mapper = mapper
        self._instructions = instructions

    async def summarise_message(self, message_id: str, user: UserContext) -> MailSummary:
        """Summarise a single message."""
        _logger.info("Summarising mailbox message")
        _logger.debug(
            "MailSummarySkill.summarise_message arguments: message_id=%s, user_id=%s",
            message_id,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        message = await self._mail_tools.get_message(message_id, user)
        return await self._summarise((message,), "Summarise this message.")

    async def summarise_thread(self, thread_id: str, user: UserContext) -> MailSummary:
        """Summarise a whole conversation."""
        _logger.info("Summarising mailbox thread")
        _logger.debug(
            "MailSummarySkill.summarise_thread arguments: thread_id=%s, user_id=%s",
            thread_id,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._summarise(
            thread.in_chronological_order(),
            "Summarise this conversation, in chronological order.",
        )

    async def summarise_messages(self, message_ids: Sequence[str], user: UserContext) -> MailSummary:
        """Summarise an arbitrary set of related messages."""
        _logger.info("Summarising mailbox message selection")
        _logger.debug(
            "MailSummarySkill.summarise_messages arguments: message_ids=%s, count=%d, user_id=%s",
            tuple(message_ids),
            len(message_ids),
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailSummarySkill")
        _logger.info("Reading messages for Mail summary loop")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return await self._summarise(tuple(messages), "Summarise these related messages.")

    async def _summarise(self, messages: Sequence[MailMessage], task: str) -> MailSummary:
        """Run the reasoner over the given messages and map the outcome."""
        _logger.info("Running Mail summary reasoning")
        _logger.debug(
            "MailSummarySkill._summarise arguments: message_ids=%s, count=%d, task_length=%d",
            tuple(message.message_id for message in messages),
            len(messages),
            len(task),
        )
        request = ReasoningRequest(
            instructions=self._instructions,
            task=task,
            context=self._context_builder.build(messages),
        )
        output = await self._reasoner.reason(request, MailSummaryOutput)
        return self._mapper.to_summary(output, messages)
