"""Extraction of the actions expected from the mailbox owner."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.mail.domain.enums import ActionOrigin
from ai_agent_lab.mail.domain.models import MailAction, MailMessage, MailSearchRequest
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.skills.analysis import MailActionsOutput, MailAnalysisMapper
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.skills.errors import EmptyMailSelectionError
from ai_agent_lab.mail.tools_port import MailReadTools

_logger = logging.getLogger(__name__)


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
        _logger.info("Initializing Mail action extraction skill")
        _logger.debug(
            "MailActionExtractionSkill.__init__ arguments: mail_tools_type=%s, "
            "reasoner_type=%s, context_builder_type=%s, mapper_type=%s, "
            "instructions_length=%d",
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

    async def extract_from_messages(
        self,
        message_ids: Sequence[str],
        user: UserContext,
    ) -> tuple[MailAction, ...]:
        """Extract the actions carried by the given messages."""
        _logger.info("Extracting actions from mailbox message selection")
        _logger.debug(
            "MailActionExtractionSkill.extract_from_messages arguments: message_ids=%s, count=%d, user_id=%s",
            tuple(message_ids),
            len(message_ids),
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailActionExtractionSkill")
        _logger.info("Reading messages for Mail action extraction loop")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return await self._extract(tuple(messages))

    async def extract_from_thread(self, thread_id: str, user: UserContext) -> tuple[MailAction, ...]:
        """Extract the actions carried by a conversation."""
        _logger.info("Extracting actions from mailbox thread")
        _logger.debug(
            "MailActionExtractionSkill.extract_from_thread arguments: thread_id=%s, user_id=%s",
            thread_id,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._extract(thread.in_chronological_order())

    async def extract_from_search(
        self,
        request: MailSearchRequest,
        user: UserContext,
    ) -> tuple[MailAction, ...]:
        """Extract the actions carried by the messages matching a query."""
        _logger.info("Extracting actions from mailbox search")
        _logger.debug(
            "MailActionExtractionSkill.extract_from_search arguments: request_type=%s, "
            "limit=%d, unread_only=%s, user_id=%s",
            type(request).__name__,
            request.limit,
            request.unread_only,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        result = await self._mail_tools.search(request, user)
        if not result.headers:
            return ()
        _logger.info("Reading Mail search result loop for action extraction")
        messages = [await self._mail_tools.get_message(header.message_id, user) for header in result.headers]
        return await self._extract(tuple(messages))

    @staticmethod
    def only_explicit(actions: Sequence[MailAction]) -> tuple[MailAction, ...]:
        """Keep the actions the messages state, dropping the deduced ones."""
        _logger.info("Filtering explicit Mail action loop")
        _logger.debug(
            "MailActionExtractionSkill.only_explicit arguments: actions=%d, source_message_ids=%s",
            len(actions),
            tuple(action.source.message_id for action in actions),
        )
        return tuple(action for action in actions if action.origin is ActionOrigin.EXPLICIT)

    async def _extract(self, messages: Sequence[MailMessage]) -> tuple[MailAction, ...]:
        """Run the reasoner over the given messages and map the outcome."""
        _logger.info("Running Mail action extraction reasoning")
        _logger.debug(
            "MailActionExtractionSkill._extract arguments: message_ids=%s, count=%d",
            tuple(message.message_id for message in messages),
            len(messages),
        )
        request = ReasoningRequest(
            instructions=self._instructions,
            task="List the actions expected from the mailbox owner.",
            context=self._context_builder.build(messages),
        )
        output = await self._reasoner.reason(request, MailActionsOutput)
        return self._mapper.to_actions(output.actions, messages)
