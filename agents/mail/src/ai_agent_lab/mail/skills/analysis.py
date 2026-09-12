"""Reasoner output models and their translation into domain models.

The shape a language model is asked to produce is a technical concern, kept
apart from the domain vocabulary. This module owns that shape and the mapping,
so every mail skill validates model output the same way.

Mapping is where grounding is enforced: a result may only reference messages
that were part of the analysed context. Otherwise untrusted content could
fabricate a source identifier and have it presented to the user as a fact.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.mail.domain.enums import ActionOrigin, ConfidenceLevel, MailCategory
from ai_agent_lab.mail.domain.models import (
    EmailAddress,
    MailAction,
    MailClassification,
    MailMessage,
    MailSourceReference,
    MailSummary,
)
from ai_agent_lab.mail.skills.categories import MailCategoryCatalog
from ai_agent_lab.mail.skills.errors import UngroundedMailResultError

_MAX_REASON_LENGTH = 280
_logger = logging.getLogger(__name__)


class ReasonerOutput(BaseModel):
    """Base class for the structures a reasoner is asked to return."""

    model_config = ConfigDict(extra="ignore")


class ExtractedActionOutput(ReasonerOutput):
    """One action the mailbox owner is expected to perform."""

    description: str
    origin: ActionOrigin = ActionOrigin.INFERRED
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    source_message_id: str
    due_date: str | None = Field(default=None, description="ISO-8601 date or date-time, or null when unknown")


class MailSummaryOutput(ReasonerOutput):
    """Structured summary of one or several messages."""

    summary: str
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    actions: list[ExtractedActionOutput] = Field(default_factory=list)


class MailActionsOutput(ReasonerOutput):
    """Actions extracted from a set of messages."""

    actions: list[ExtractedActionOutput] = Field(default_factory=list)


class MailClassificationOutput(ReasonerOutput):
    """Category proposed for a single message."""

    category: MailCategory = MailCategory.OTHER
    confidence: float = 0.5
    reason: str = ""


class MailReplyOutput(ReasonerOutput):
    """A drafted reply."""

    subject: str
    body: str


class MailAnalysisMapper:
    """Translates reasoner output into domain models.

    Args:
        category_catalog: Catalogue deciding which categories are acceptable.
    """

    def __init__(self, category_catalog: MailCategoryCatalog) -> None:
        _logger.info("Initializing Mail analysis mapper")
        _logger.debug(
            "MailAnalysisMapper.__init__ arguments: category_catalog_type=%s",
            type(category_catalog).__name__,
        )
        self._category_catalog = category_catalog

    def to_summary(
        self,
        output: MailSummaryOutput,
        messages: Sequence[MailMessage],
    ) -> MailSummary:
        """Build a domain summary grounded in the analysed messages."""
        _logger.info("Mapping Mail summary analysis")
        _logger.debug(
            "MailAnalysisMapper.to_summary arguments: message_ids=%s, messages=%d, "
            "key_points=%d, decisions=%d, uncertainties=%d, actions=%d",
            tuple(message.message_id for message in messages),
            len(messages),
            len(output.key_points),
            len(output.decisions),
            len(output.uncertainties),
            len(output.actions),
        )
        actions = self.to_actions(output.actions, messages)
        return MailSummary(
            summary=output.summary.strip(),
            key_points=tuple(self._clean(output.key_points)),
            decisions=tuple(self._clean(output.decisions)),
            uncertainties=tuple(self._clean(output.uncertainties)),
            actions=actions,
            deadlines=tuple(action.due_date for action in actions if action.due_date is not None),
            participants=self._participants_of(messages),
            sources=self._sources_of(messages),
        )

    def to_actions(
        self,
        outputs: Iterable[ExtractedActionOutput],
        messages: Sequence[MailMessage],
    ) -> tuple[MailAction, ...]:
        """Build domain actions, rejecting any ungrounded source reference."""
        _logger.info("Mapping Mail action output loop")
        _logger.debug(
            "MailAnalysisMapper.to_actions arguments: outputs_type=%s, message_ids=%s, messages=%d",
            type(outputs).__name__,
            tuple(message.message_id for message in messages),
            len(messages),
        )
        by_id = {message.message_id: message for message in messages}
        return tuple(self._to_action(output, by_id) for output in outputs if output.description.strip())

    def to_classification(
        self,
        output: MailClassificationOutput,
        message: MailMessage,
    ) -> MailClassification:
        """Build a domain classification, normalising category and confidence."""
        _logger.info("Mapping Mail classification analysis")
        _logger.debug(
            "MailAnalysisMapper.to_classification arguments: message_id=%s, "
            "category=%s, confidence=%s, reason_length=%d",
            message.message_id,
            output.category.value,
            output.confidence,
            len(output.reason),
        )
        return MailClassification(
            message_id=message.message_id,
            category=self._category_catalog.normalise(output.category),
            confidence=min(max(output.confidence, 0.0), 1.0),
            reason=output.reason.strip()[:_MAX_REASON_LENGTH],
        )

    def _to_action(
        self,
        output: ExtractedActionOutput,
        messages_by_id: dict[str, MailMessage],
    ) -> MailAction:
        """Build one domain action from a reasoner entry."""
        _logger.debug(
            "MailAnalysisMapper._to_action arguments: source_message_id=%s, "
            "description_length=%d, origin=%s, confidence=%s, due_date_present=%s, "
            "available_messages=%d",
            output.source_message_id,
            len(output.description),
            output.origin.value,
            output.confidence.value,
            output.due_date is not None,
            len(messages_by_id),
        )
        message = messages_by_id.get(output.source_message_id)
        if message is None:
            raise UngroundedMailResultError(output.source_message_id)
        return MailAction(
            description=output.description.strip(),
            origin=output.origin,
            confidence=output.confidence,
            source=MailSourceReference(message_id=message.message_id, thread_id=message.thread_id),
            due_date=self._parse_due_date(output.due_date),
        )

    @staticmethod
    def _parse_due_date(value: str | None) -> datetime | None:
        """Parse an optional due date.

        A due date is inferred information. When it cannot be parsed it is
        reported as unknown rather than invented, and the action itself is kept
        because its description remains useful.
        """
        _logger.debug(
            "MailAnalysisMapper._parse_due_date arguments: present=%s, value_length=%s",
            value is not None,
            None if value is None else len(value),
        )
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _clean(values: Iterable[str]) -> tuple[str, ...]:
        """Drop blank entries and surrounding whitespace."""
        _logger.info("Cleaning Mail analysis output loop")
        _logger.debug(
            "MailAnalysisMapper._clean arguments: values_type=%s",
            type(values).__name__,
        )
        return tuple(stripped for stripped in (value.strip() for value in values) if stripped)

    @staticmethod
    def _participants_of(messages: Sequence[MailMessage]) -> tuple[EmailAddress, ...]:
        """Distinct participants of the analysed messages, in order."""
        _logger.info("Collecting Mail analysis participant loop")
        _logger.debug(
            "MailAnalysisMapper._participants_of arguments: message_ids=%s, messages=%d",
            tuple(message.message_id for message in messages),
            len(messages),
        )
        seen: dict[str, EmailAddress] = {}
        for message in messages:
            for participant in (message.sender, *message.to, *message.cc):
                seen.setdefault(participant.address.value, participant.address)
        return tuple(seen.values())

    @staticmethod
    def _sources_of(messages: Sequence[MailMessage]) -> tuple[MailSourceReference, ...]:
        """Reference every analysed message as a source."""
        _logger.info("Collecting Mail analysis source loop")
        _logger.debug(
            "MailAnalysisMapper._sources_of arguments: message_ids=%s, messages=%d",
            tuple(message.message_id for message in messages),
            len(messages),
        )
        return tuple(
            MailSourceReference(message_id=message.message_id, thread_id=message.thread_id) for message in messages
        )
