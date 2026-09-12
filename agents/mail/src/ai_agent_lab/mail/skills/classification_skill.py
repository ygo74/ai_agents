"""Classification of messages into configurable business categories."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ai_agent_lab.core.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.models import MailClassification, MailMessage
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.skills.analysis import MailAnalysisMapper, MailClassificationOutput
from ai_agent_lab.mail.skills.categories import MailCategoryCatalog
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.skills.errors import EmptyMailSelectionError
from ai_agent_lab.mail.tools_port import MailReadTools

_logger = logging.getLogger(__name__)


class MailClassificationSkill:
    """Assigns a category to a message, a thread or a set of messages.

    The catalogue of categories is injected, so a deployment can restrict or
    re-word them without touching this class or the agent. The reasoning
    instructions are injected for the same reason.
    """

    def __init__(
        self,
        mail_tools: MailReadTools,
        reasoner: TextReasoner,
        context_builder: MailContextBuilder,
        mapper: MailAnalysisMapper,
        category_catalog: MailCategoryCatalog,
        instructions: str,
    ) -> None:
        _logger.info("Initializing Mail classification skill")
        _logger.debug(
            "MailClassificationSkill.__init__ arguments: mail_tools_type=%s, "
            "reasoner_type=%s, context_builder_type=%s, mapper_type=%s, "
            "category_catalog_type=%s, instructions_length=%d",
            type(mail_tools).__name__,
            type(reasoner).__name__,
            type(context_builder).__name__,
            type(mapper).__name__,
            type(category_catalog).__name__,
            len(instructions),
        )
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._mapper = mapper
        self._category_catalog = category_catalog
        self._instructions = instructions

    async def classify_message(self, message_id: str, user: UserContext) -> MailClassification:
        """Classify a single message."""
        _logger.info("Classifying mailbox message")
        _logger.debug(
            "MailClassificationSkill.classify_message arguments: message_id=%s, user_id=%s",
            message_id,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        message = await self._mail_tools.get_message(message_id, user)
        return await self._classify(message)

    async def classify_messages(
        self,
        message_ids: Sequence[str],
        user: UserContext,
    ) -> tuple[MailClassification, ...]:
        """Classify several messages, one decision per message."""
        _logger.info("Classifying mailbox message selection")
        _logger.debug(
            "MailClassificationSkill.classify_messages arguments: message_ids=%s, count=%d, user_id=%s",
            tuple(message_ids),
            len(message_ids),
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailClassificationSkill")
        _logger.info("Reading and classifying Mail message loop")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return tuple([await self._classify(message) for message in messages])

    async def classify_thread(self, thread_id: str, user: UserContext) -> MailClassification:
        """Classify a conversation through its most recent message."""
        _logger.info("Classifying mailbox thread")
        _logger.debug(
            "MailClassificationSkill.classify_thread arguments: thread_id=%s, user_id=%s",
            thread_id,
            user.user_id,
        )
        user.require_permission(MailPermission.READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._classify(thread.latest_message, context=thread.in_chronological_order())

    async def _classify(
        self,
        message: MailMessage,
        *,
        context: Sequence[MailMessage] | None = None,
    ) -> MailClassification:
        """Run the reasoner over one message and map the outcome."""
        _logger.debug(
            "MailClassificationSkill._classify arguments: message_id=%s, context_count=%d",
            message.message_id,
            1 if context is None else len(context),
        )
        request = ReasoningRequest(
            instructions=f"{self._instructions}\n{self._category_catalog.describe()}",
            task=f"Classify the message whose message_id is {message.message_id}.",
            context=self._context_builder.build(context or (message,)),
        )
        output = await self._reasoner.reason(request, MailClassificationOutput)
        return self._mapper.to_classification(output, message)
