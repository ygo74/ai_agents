"""Summarisation of a message, a thread or a set of related messages."""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.domain.mail.models import MailMessage, MailSummary
from ai_agent_lab.domain.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.mcp.mail.contracts import MailReadTools
from ai_agent_lab.skills.mail.analysis import MailAnalysisMapper, MailSummaryOutput
from ai_agent_lab.skills.mail.context import MailContextBuilder
from ai_agent_lab.skills.mail.errors import EmptyMailSelectionError

_INSTRUCTIONS = (
    "You are a mail analyst working for the owner of the mailbox.\n"
    "Summarise only what the provided messages actually say.\n"
    "Never invent a fact, a name, a date or a decision.\n"
    "Separate what is stated from what you deduce: put deduced items in "
    "'uncertainties' or mark the corresponding action as INFERRED.\n"
    "Every action must reference the message_id it comes from."
)


class MailSummarySkill:
    """Produces a structured summary grounded in retrieved messages.

    Retrieval is delegated to the MCP layer and reasoning to the injected
    :class:`TextReasoner`, so the skill itself stays free of both transport and
    framework concerns.
    """

    def __init__(
        self,
        mail_tools: MailReadTools,
        reasoner: TextReasoner,
        context_builder: MailContextBuilder,
        mapper: MailAnalysisMapper,
    ) -> None:
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._mapper = mapper

    async def summarise_message(self, message_id: str, user: UserContext) -> MailSummary:
        """Summarise a single message."""
        user.require_permission(Permission.MAIL_READ)
        message = await self._mail_tools.get_message(message_id, user)
        return await self._summarise((message,), "Summarise this message.")

    async def summarise_thread(self, thread_id: str, user: UserContext) -> MailSummary:
        """Summarise a whole conversation."""
        user.require_permission(Permission.MAIL_READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._summarise(
            thread.in_chronological_order(),
            "Summarise this conversation, in chronological order.",
        )

    async def summarise_messages(self, message_ids: Sequence[str], user: UserContext) -> MailSummary:
        """Summarise an arbitrary set of related messages."""
        user.require_permission(Permission.MAIL_READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailSummarySkill")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return await self._summarise(tuple(messages), "Summarise these related messages.")

    async def _summarise(self, messages: Sequence[MailMessage], task: str) -> MailSummary:
        """Run the reasoner over the given messages and map the outcome."""
        request = ReasoningRequest(
            instructions=_INSTRUCTIONS,
            task=task,
            context=self._context_builder.build(messages),
        )
        output = await self._reasoner.reason(request, MailSummaryOutput)
        return self._mapper.to_summary(output, messages)
