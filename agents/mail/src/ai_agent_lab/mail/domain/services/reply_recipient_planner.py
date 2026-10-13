"""Deterministic recipient rules independent of drafting and reasoning."""

from __future__ import annotations

import logging

from ai_agent_lab.mail.domain.errors import NoReplyRecipientError
from ai_agent_lab.mail.domain.models import EmailAddress, MailMessage, MailParticipant

_logger = logging.getLogger(__name__)


class ReplyRecipientPlanner:
    """Choose recipients, excluding the owner and duplicate addresses."""

    def plan(
        self,
        message: MailMessage,
        owner: EmailAddress,
        *,
        reply_all: bool,
    ) -> tuple[tuple[EmailAddress, ...], tuple[EmailAddress, ...]]:
        """Return the ``to`` and ``cc`` lists of a reply."""
        _logger.info("Planning Mail reply recipients")
        _logger.debug(
            "ReplyRecipientPlanner.plan arguments: message_id=%s, to_count=%d, cc_count=%d, reply_all=%s",
            message.message_id,
            len(message.to),
            len(message.cc),
            reply_all,
        )
        primary = self._unique((message.sender,), exclude={owner})
        if not reply_all:
            return self._require_recipients(primary, message), ()

        others = self._unique((*message.to, *message.cc), exclude={owner, *primary})
        if primary:
            return primary, others
        return self._require_recipients(others, message), ()

    @staticmethod
    def _unique(
        participants: tuple[MailParticipant, ...],
        *,
        exclude: set[EmailAddress],
    ) -> tuple[EmailAddress, ...]:
        """Collect distinct addresses, dropping the excluded ones."""
        _logger.info("Collecting unique Mail reply recipient loop")
        _logger.debug(
            "ReplyRecipientPlanner._unique arguments: participants=%d, excluded=%d",
            len(participants),
            len(exclude),
        )
        seen: dict[str, EmailAddress] = {}
        for participant in participants:
            address = participant.address
            if address in exclude:
                continue
            seen.setdefault(address.value, address)
        return tuple(seen.values())

    @staticmethod
    def _require_recipients(
        recipients: tuple[EmailAddress, ...],
        message: MailMessage,
    ) -> tuple[EmailAddress, ...]:
        """Fail rather than produce a reply nobody would receive."""
        _logger.info("Validating Mail reply recipients")
        _logger.debug(
            "ReplyRecipientPlanner._require_recipients arguments: recipients=%d, message_id=%s",
            len(recipients),
            message.message_id,
        )
        if not recipients:
            raise NoReplyRecipientError(message.message_id)
        return recipients
