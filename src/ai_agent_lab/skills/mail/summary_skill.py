"""Summarisation of a message, a thread or a set of related messages."""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.domain.mail.models import MailMessage, MailSummary
from ai_agent_lab.domain.mail.permissions import MailPermission
from ai_agent_lab.domain.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.mcp.mail.contracts import MailReadTools
from ai_agent_lab.skills.mail.analysis import MailAnalysisMapper, MailSummaryOutput
from ai_agent_lab.skills.mail.context import MailContextBuilder
from ai_agent_lab.skills.mail.errors import EmptyMailSelectionError


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
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._mapper = mapper
        self._instructions = instructions

    async def summarise_message(self, message_id: str, user: UserContext) -> MailSummary:
        """Summarise a single message."""
        user.require_permission(MailPermission.READ)
        message = await self._mail_tools.get_message(message_id, user)
        return await self._summarise((message,), "Summarise this message.")

    async def summarise_thread(self, thread_id: str, user: UserContext) -> MailSummary:
        """Summarise a whole conversation."""
        user.require_permission(MailPermission.READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._summarise(
            thread.in_chronological_order(),
            "Summarise this conversation, in chronological order.",
        )

    async def summarise_messages(self, message_ids: Sequence[str], user: UserContext) -> MailSummary:
        """Summarise an arbitrary set of related messages."""
        user.require_permission(MailPermission.READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailSummarySkill")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return await self._summarise(tuple(messages), "Summarise these related messages.")

    async def _summarise(self, messages: Sequence[MailMessage], task: str) -> MailSummary:
        """Run the reasoner over the given messages and map the outcome."""
        request = ReasoningRequest(
            instructions=self._instructions,
            task=task,
            context=self._context_builder.build(messages),
        )
        output = await self._reasoner.reason(request, MailSummaryOutput)
        return self._mapper.to_summary(output, messages)
