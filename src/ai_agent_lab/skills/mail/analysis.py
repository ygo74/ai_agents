"""Reasoner output models and their translation into domain models.

The shape a language model is asked to produce is a technical concern, kept
apart from the domain vocabulary. This module owns that shape and the mapping,
so every mail skill validates model output the same way.

Mapping is where grounding is enforced: a result may only reference messages
that were part of the analysed context. Otherwise untrusted content could
fabricate a source identifier and have it presented to the user as a fact.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.domain.mail.enums import ActionOrigin, ConfidenceLevel, MailCategory
from ai_agent_lab.domain.mail.models import (
    EmailAddress,
    MailAction,
    MailClassification,
    MailMessage,
    MailSourceReference,
    MailSummary,
)
from ai_agent_lab.skills.mail.categories import MailCategoryCatalog
from ai_agent_lab.skills.mail.errors import UngroundedMailResultError

_MAX_REASON_LENGTH = 280


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
        self._category_catalog = category_catalog

    def to_summary(
        self,
        output: MailSummaryOutput,
        messages: Sequence[MailMessage],
    ) -> MailSummary:
        """Build a domain summary grounded in the analysed messages."""
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
        by_id = {message.message_id: message for message in messages}
        return tuple(self._to_action(output, by_id) for output in outputs if output.description.strip())

    def to_classification(
        self,
        output: MailClassificationOutput,
        message: MailMessage,
    ) -> MailClassification:
        """Build a domain classification, normalising category and confidence."""
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
        return tuple(stripped for stripped in (value.strip() for value in values) if stripped)

    @staticmethod
    def _participants_of(messages: Sequence[MailMessage]) -> tuple[EmailAddress, ...]:
        """Distinct participants of the analysed messages, in order."""
        seen: dict[str, EmailAddress] = {}
        for message in messages:
            for participant in (message.sender, *message.to, *message.cc):
                seen.setdefault(participant.address.value, participant.address)
        return tuple(seen.values())

    @staticmethod
    def _sources_of(messages: Sequence[MailMessage]) -> tuple[MailSourceReference, ...]:
        """Reference every analysed message as a source."""
        return tuple(
            MailSourceReference(message_id=message.message_id, thread_id=message.thread_id) for message in messages
        )
