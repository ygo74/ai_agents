"""Assembly of the untrusted context handed to a reasoner.

Turning messages into reasoning context is shared by summarisation,
classification, action extraction and reply drafting, so it lives in one place.
Sections keep the :class:`UntrustedText` wrapper all the way to the prompt
envelope, which is the only component allowed to render them.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ai_agent_lab.core.reasoning.ports import UntrustedSection
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, UntrustedText, untrusted
from ai_agent_lab.mail.domain.models import MailMessage, MailParticipant

_TRUNCATION_NOTICE = "\n[... truncated ...]"
_logger = logging.getLogger(__name__)


class MailContextBuilder:
    """Builds labelled untrusted sections out of messages.

    Args:
        max_body_characters: Upper bound applied to each body. Bodies are
            truncated rather than dropped, so a long newsletter cannot push the
            rest of a conversation out of the context window.
    """

    def __init__(self, *, max_body_characters: int = 4000) -> None:
        _logger.info("Initializing Mail reasoning context builder")
        _logger.debug(
            "MailContextBuilder.__init__ arguments: max_body_characters=%d",
            max_body_characters,
        )
        self._max_body_characters = max_body_characters

    def build(self, messages: Iterable[MailMessage]) -> tuple[UntrustedSection, ...]:
        """Build one section per message, preserving the given order."""
        materialized = tuple(messages)
        _logger.info("Building Mail reasoning context loop")
        _logger.debug(
            "MailContextBuilder.build arguments: message_ids=%s, count=%d",
            tuple(message.message_id for message in materialized),
            len(materialized),
        )
        return tuple(self._section_for(message) for message in materialized)

    def _section_for(self, message: MailMessage) -> UntrustedSection:
        """Build the section describing a single message."""
        _logger.debug(
            "MailContextBuilder._section_for arguments: message_id=%s, thread_id=%s",
            message.message_id,
            message.thread_id,
        )
        return UntrustedSection(label=self._label_for(message), content=self._content_of(message))

    @staticmethod
    def _label_for(message: MailMessage) -> str:
        """Build a label made only of trusted metadata.

        The label carries identifiers and a timestamp, never third-party text,
        so it cannot become an injection vector of its own.
        """
        _logger.debug(
            "MailContextBuilder._label_for arguments: message_id=%s, thread_id=%s, sent_at=%s",
            message.message_id,
            message.thread_id,
            message.sent_at.isoformat(),
        )
        return f"message_id={message.message_id} thread_id={message.thread_id} sent_at={message.sent_at.isoformat()}"

    def _content_of(self, message: MailMessage) -> UntrustedText:
        """Merge the envelope and the body of a message into one untrusted block.

        Exposing the fragments here is deliberate and local: the result is
        immediately re-wrapped, so the merged text never escapes the untrusted
        world.
        """
        _logger.debug(
            "MailContextBuilder._content_of arguments: message_id=%s, to_count=%d, "
            "cc_count=%d, subject_length=%d, body_length=%d",
            message.message_id,
            len(message.to),
            len(message.cc),
            len(message.subject.expose()),
            len(message.body.expose()),
        )
        recipients = ", ".join(self._describe(participant) for participant in message.to) or "(none)"
        lines = [f"From: {self._describe(message.sender)}", f"To: {recipients}"]
        if message.cc:
            lines.append(f"Cc: {', '.join(self._describe(participant) for participant in message.cc)}")
        lines.append(f"Subject: {message.subject.expose()}")
        lines.append("")
        lines.append(self._truncate(message.body.expose()))
        return untrusted("\n".join(lines), UntrustedOrigin.MAIL_BODY)

    @staticmethod
    def _describe(participant: MailParticipant) -> str:
        """Render a participant, display name included when present."""
        _logger.debug(
            "MailContextBuilder._describe arguments: display_name_present=%s",
            participant.display_name is not None,
        )
        if participant.display_name is None:
            return str(participant.address)
        return f"{participant.display_name.expose()} <{participant.address}>"

    def _truncate(self, body: str) -> str:
        """Shorten a body that exceeds the configured budget."""
        _logger.debug(
            "MailContextBuilder._truncate arguments: body_length=%d, limit=%d",
            len(body),
            self._max_body_characters,
        )
        if len(body) <= self._max_body_characters:
            return body
        return body[: self._max_body_characters] + _TRUNCATION_NOTICE
