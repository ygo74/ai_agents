"""Extraction of the actions expected from the mailbox owner."""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.enums import ActionOrigin
from ai_agent_lab.mail.domain.models import MailAction, MailMessage, MailSearchRequest
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.skills.analysis import MailActionsOutput, MailAnalysisMapper
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.skills.errors import EmptyMailSelectionError
from ai_agent_lab.mail.tools_port import MailReadTools


class MailActionExtractionSkill:
    """Identifies what the mailbox owner has to do, and where it comes from.

    Explicit and inferred actions are kept apart so the agent never presents a
    deduction as a fact. The reasoning instructions are injected: they are
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

    async def extract_from_messages(
        self,
        message_ids: Sequence[str],
        user: UserContext,
    ) -> tuple[MailAction, ...]:
        """Extract the actions carried by the given messages."""
        user.require_permission(MailPermission.READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailActionExtractionSkill")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return await self._extract(tuple(messages))

    async def extract_from_thread(self, thread_id: str, user: UserContext) -> tuple[MailAction, ...]:
        """Extract the actions carried by a conversation."""
        user.require_permission(MailPermission.READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._extract(thread.in_chronological_order())

    async def extract_from_search(
        self,
        request: MailSearchRequest,
        user: UserContext,
    ) -> tuple[MailAction, ...]:
        """Extract the actions carried by the messages matching a query."""
        user.require_permission(MailPermission.READ)
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
            instructions=self._instructions,
            task="List the actions expected from the mailbox owner.",
            context=self._context_builder.build(messages),
        )
        output = await self._reasoner.reason(request, MailActionsOutput)
        return self._mapper.to_actions(output.actions, messages)
