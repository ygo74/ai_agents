"""Classification of messages into configurable business categories."""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent_lab.domain.mail.models import MailClassification, MailMessage
from ai_agent_lab.domain.reasoning.ports import ReasoningRequest, TextReasoner
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.mcp.mail.contracts import MailReadTools
from ai_agent_lab.skills.mail.analysis import MailAnalysisMapper, MailClassificationOutput
from ai_agent_lab.skills.mail.categories import MailCategoryCatalog
from ai_agent_lab.skills.mail.context import MailContextBuilder
from ai_agent_lab.skills.mail.errors import EmptyMailSelectionError

_INSTRUCTIONS = (
    "You are a mail analyst working for the owner of the mailbox.\n"
    "Assign exactly one category from the catalogue below.\n"
    "Base the decision only on what the message says.\n"
    "Give a confidence between 0 and 1 and a reason of at most two sentences.\n"
    "\n"
    "Categories:\n"
)


class MailClassificationSkill:
    """Assigns a category to a message, a thread or a set of messages.

    The catalogue of categories is injected, so a deployment can restrict or
    re-word them without touching this class or the agent.
    """

    def __init__(
        self,
        mail_tools: MailReadTools,
        reasoner: TextReasoner,
        context_builder: MailContextBuilder,
        mapper: MailAnalysisMapper,
        category_catalog: MailCategoryCatalog,
    ) -> None:
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._context_builder = context_builder
        self._mapper = mapper
        self._category_catalog = category_catalog

    async def classify_message(self, message_id: str, user: UserContext) -> MailClassification:
        """Classify a single message."""
        user.require_permission(Permission.MAIL_READ)
        message = await self._mail_tools.get_message(message_id, user)
        return await self._classify(message)

    async def classify_messages(
        self,
        message_ids: Sequence[str],
        user: UserContext,
    ) -> tuple[MailClassification, ...]:
        """Classify several messages, one decision per message."""
        user.require_permission(Permission.MAIL_READ)
        if not message_ids:
            raise EmptyMailSelectionError("MailClassificationSkill")
        messages = [await self._mail_tools.get_message(message_id, user) for message_id in message_ids]
        return tuple([await self._classify(message) for message in messages])

    async def classify_thread(self, thread_id: str, user: UserContext) -> MailClassification:
        """Classify a conversation through its most recent message."""
        user.require_permission(Permission.MAIL_READ)
        thread = await self._mail_tools.get_thread(thread_id, user)
        return await self._classify(thread.latest_message, context=thread.in_chronological_order())

    async def _classify(
        self,
        message: MailMessage,
        *,
        context: Sequence[MailMessage] | None = None,
    ) -> MailClassification:
        """Run the reasoner over one message and map the outcome."""
        request = ReasoningRequest(
            instructions=_INSTRUCTIONS + self._category_catalog.describe(),
            task=f"Classify the message whose message_id is {message.message_id}.",
            context=self._context_builder.build(context or (message,)),
        )
        output = await self._reasoner.reason(request, MailClassificationOutput)
        return self._mapper.to_classification(output, message)
