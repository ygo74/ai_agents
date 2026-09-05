"""Extraction of the actions expected from the mailbox owner."""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.domain.mail.enums import ActionOrigin
from ai_agent_lab.domain.mail.models import MailAction, MailMessage, MailSearchRequest
from ai_agent_lab.domain.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.mcp.mail.contracts import MailReadTools
from ai_agent_lab.skills.mail.analysis import MailActionsOutput, MailAnalysisMapper
from ai_agent_lab.skills.mail.context import MailContextBuilder
from ai_agent_lab.skills.mail.errors import EmptyMailSelectionError

_INSTRUCTIONS = (
    "You are a mail analyst working for the owner of the mailbox.\n"
    "List only the actions the mailbox owner is expected to perform.\n"
    "Ignore actions assigned to somebody else.\n"
    "Mark an action EXPLICIT when the message states the request, and INFERRED "
    "when you deduced it. Never present a deduced action as stated.\n"
    "Set a due date only when the message gives one; otherwise leave it null.\n"
    "Every action must reference the message_id it comes from."
)


class MailActionExtractionSkill:
    """Identifies what the mailbox owner has to do, and where it comes from.

    Explicit and inferred actions are kept apart so the agent never presents a
    deduction as a fact.
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

    async def extract_from_messages(
        self,
        message_ids: Sequence[str],
        user: UserContext,
    ) -> tuple[MailAction, ...]:
        """Extract the actions carried by the given messages."""
        user.require_permission(Permission.MAIL_READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailActionExtractionSkill")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return await self._extract(tuple(messages))

    async def extract_from_thread(self, thread_id: str, user: UserContext) -> tuple[MailAction, ...]:
        """Extract the actions carried by a conversation."""
        user.require_permission(Permission.MAIL_READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._extract(thread.in_chronological_order())

    async def extract_from_search(
        self,
        request: MailSearchRequest,
        user: UserContext,
    ) -> tuple[MailAction, ...]:
        """Extract the actions carried by the messages matching a query."""
        user.require_permission(Permission.MAIL_READ)
        result = await self._mail_tools.search(request, user)
        if not result.headers:
            return ()
        messages = [await self._mail_tools.get_message(header.message_id, user) for header in result.headers]
        return await self._extract(tuple(messages))

    @staticmethod
    def only_explicit(actions: Sequence[MailAction]) -> tuple[MailAction, ...]:
        """Keep the actions the messages state, dropping the deduced ones."""
        return tuple(action for action in actions if action.origin is ActionOrigin.EXPLICIT)

    async def _extract(self, messages: Sequence[MailMessage]) -> tuple[MailAction, ...]:
        """Run the reasoner over the given messages and map the outcome."""
        request = ReasoningRequest(
            instructions=_INSTRUCTIONS,
            task="List the actions expected from the mailbox owner.",
            context=self._context_builder.build(messages),
        )
        output = await self._reasoner.reason(request, MailActionsOutput)
        return self._mapper.to_actions(output.actions, messages)
