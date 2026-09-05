"""Assembly of the untrusted context handed to a reasoner.

Turning messages into reasoning context is shared by summarisation,
classification, action extraction and reply drafting, so it lives in one place.
Sections keep the :class:`UntrustedText` wrapper all the way to the prompt
envelope, which is the only component allowed to render them.
"""

from __future__ import annotations

from collections.abc import Iterable

from ai_agent_lab.domain.mail.models import MailMessage, MailParticipant
from ai_agent_lab.domain.reasoning.ports import UntrustedSection
from ai_agent_lab.domain.security.untrusted import UntrustedOrigin, UntrustedText, untrusted

_TRUNCATION_NOTICE = "\n[... truncated ...]"


class MailContextBuilder:
    """Builds labelled untrusted sections out of messages.

    Args:
        max_body_characters: Upper bound applied to each body. Bodies are
            truncated rather than dropped, so a long newsletter cannot push the
            rest of a conversation out of the context window.
    """

    def __init__(self, *, max_body_characters: int = 4000) -> None:
        self._max_body_characters = max_body_characters

    def build(self, messages: Iterable[MailMessage]) -> tuple[UntrustedSection, ...]:
        """Build one section per message, preserving the given order."""
        return tuple(self._section_for(message) for message in messages)

    def _section_for(self, message: MailMessage) -> UntrustedSection:
        """Build the section describing a single message."""
        return UntrustedSection(label=self._label_for(message), content=self._content_of(message))

    @staticmethod
    def _label_for(message: MailMessage) -> str:
        """Build a label made only of trusted metadata.

        The label carries identifiers and a timestamp, never third-party text,
        so it cannot become an injection vector of its own.
        """
        return f"message_id={message.message_id} thread_id={message.thread_id} sent_at={message.sent_at.isoformat()}"

    def _content_of(self, message: MailMessage) -> UntrustedText:
        """Merge the envelope and the body of a message into one untrusted block.

        Exposing the fragments here is deliberate and local: the result is
        immediately re-wrapped, so the merged text never escapes the untrusted
        world.
        """
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
        if participant.display_name is None:
            return str(participant.address)
        return f"{participant.display_name.expose()} <{participant.address}>"

    def _truncate(self, body: str) -> str:
        """Shorten a body that exceeds the configured budget."""
        if len(body) <= self._max_body_characters:
            return body
        return body[: self._max_body_characters] + _TRUNCATION_NOTICE
