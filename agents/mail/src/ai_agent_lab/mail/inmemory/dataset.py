"""Loading of mailbox datasets stored as JSON.

Datasets are the reproducible input of the mock runtime mode and of the agent
scenarios. Everything the loader reads was written by a third party, so every
piece of free text is wrapped as untrusted content on the way in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ygo74.agent_runtime.domains.security.untrusted import untrusted

from ai_agent_lab.mail.domain.enums import MailImportance
from ai_agent_lab.mail.domain.models import (
    EmailAddress,
    MailAttachment,
    MailLabel,
    MailMessage,
    MailParticipant,
)
from ai_agent_lab.mail.domain.origins import MailOrigin
from ai_agent_lab.mail.inmemory.mail_tools import Mailbox
from ai_agent_lab.mail.mail_errors import MailToolProtocolError

JsonObject = Mapping[str, Any]
_logger = logging.getLogger(__name__)


class MailDatasetError(MailToolProtocolError):
    """Raised when a dataset cannot be turned into domain models."""


class MailDatasetLoader:
    """Builds mailboxes from a JSON description."""

    def load_file(self, path: Path) -> dict[str, Mailbox]:
        """Load every mailbox described by a JSON file."""
        _logger.info("Loading in-memory Mail dataset file")
        _logger.debug("MailDatasetLoader.load_file arguments: file_name=%s", path.name)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MailDatasetError(f"could not read mail dataset {path}: {error}") from error
        return self.load(raw)

    def load(self, raw: JsonObject) -> dict[str, Mailbox]:
        """Load every mailbox described by a decoded JSON object."""
        _logger.info("Building in-memory mailbox loop from dataset")
        _logger.debug(
            "MailDatasetLoader.load arguments: top_level_keys=%s",
            tuple(sorted(raw)),
        )
        mailboxes = raw.get("mailboxes")
        if not isinstance(mailboxes, list):
            raise MailDatasetError("dataset must contain a 'mailboxes' list")
        return {mailbox.owner_id: mailbox for mailbox in (self._build_mailbox(entry) for entry in mailboxes)}

    def _build_mailbox(self, entry: JsonObject) -> Mailbox:
        """Build one mailbox from its JSON description."""
        _logger.debug(
            "MailDatasetLoader._build_mailbox arguments: entry_keys=%s",
            tuple(sorted(entry)),
        )
        owner_id = self._require_str(entry, "owner_id")
        _logger.info("Building labels and messages for in-memory mailbox loops")
        labels = [self._build_label(item) for item in self._sequence(entry, "labels")]
        messages = [self._build_message(item) for item in self._sequence(entry, "messages")]
        return Mailbox(owner_id=owner_id, messages=messages, labels=labels)

    def _build_label(self, entry: JsonObject) -> MailLabel:
        """Build one label from its JSON description."""
        _logger.debug(
            "MailDatasetLoader._build_label arguments: entry_keys=%s",
            tuple(sorted(entry)),
        )
        return MailLabel(
            label_id=self._require_str(entry, "label_id"),
            name=untrusted(self._require_str(entry, "name"), MailOrigin.LABEL),
            is_system=bool(entry.get("is_system", False)),
        )

    def _build_message(self, entry: JsonObject) -> MailMessage:
        """Build one message from its JSON description."""
        _logger.debug(
            "MailDatasetLoader._build_message arguments: entry_keys=%s",
            tuple(sorted(entry)),
        )
        try:
            _logger.info("Building participants and attachments for in-memory message loops")
            return MailMessage(
                message_id=self._require_str(entry, "message_id"),
                thread_id=self._require_str(entry, "thread_id"),
                subject=untrusted(self._require_str(entry, "subject"), MailOrigin.SUBJECT),
                body=untrusted(self._require_str(entry, "body"), MailOrigin.BODY),
                sender=self._build_participant(entry["sender"]),
                to=tuple(self._build_participant(item) for item in self._sequence(entry, "to")),
                cc=tuple(self._build_participant(item) for item in self._sequence(entry, "cc")),
                sent_at=self._parse_datetime(self._require_str(entry, "sent_at")),
                is_read=bool(entry.get("is_read", False)),
                is_archived=bool(entry.get("is_archived", False)),
                importance=MailImportance(entry.get("importance", MailImportance.NORMAL.value)),
                label_ids=tuple(str(item) for item in self._sequence(entry, "label_ids")),
                attachments=tuple(self._build_attachment(item) for item in self._sequence(entry, "attachments")),
                in_reply_to=entry.get("in_reply_to"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise MailDatasetError(f"invalid message entry: {error}") from error

    def _build_participant(self, entry: JsonObject) -> MailParticipant:
        """Build one participant from its JSON description."""
        _logger.debug(
            "MailDatasetLoader._build_participant arguments: entry_keys=%s",
            tuple(sorted(entry)),
        )
        display_name = entry.get("display_name")
        return MailParticipant(
            address=EmailAddress(value=self._require_str(entry, "address")),
            display_name=(
                None if display_name is None else untrusted(str(display_name), MailOrigin.SENDER_NAME)
            ),
        )

    def _build_attachment(self, entry: JsonObject) -> MailAttachment:
        """Build one attachment from its JSON description."""
        _logger.debug(
            "MailDatasetLoader._build_attachment arguments: entry_keys=%s",
            tuple(sorted(entry)),
        )
        return MailAttachment(
            attachment_id=self._require_str(entry, "attachment_id"),
            file_name=untrusted(self._require_str(entry, "file_name"), MailOrigin.ATTACHMENT_NAME),
            media_type=self._require_str(entry, "media_type"),
            size_bytes=int(entry.get("size_bytes", 0)),
        )

    @staticmethod
    def _require_str(entry: JsonObject, key: str) -> str:
        """Return a mandatory string field."""
        _logger.debug(
            "MailDatasetLoader._require_str arguments: key=%s, entry_keys=%s",
            key,
            tuple(sorted(entry)),
        )
        value = entry.get(key)
        if not isinstance(value, str):
            raise MailDatasetError(f"field {key!r} must be a string")
        return value

    @staticmethod
    def _sequence(entry: JsonObject, key: str) -> Sequence[Any]:
        """Return an optional list field, defaulting to an empty one."""
        _logger.debug(
            "MailDatasetLoader._sequence arguments: key=%s, entry_keys=%s",
            key,
            tuple(sorted(entry)),
        )
        value = entry.get(key, [])
        if not isinstance(value, list):
            raise MailDatasetError(f"field {key!r} must be a list")
        return value

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        """Parse an ISO-8601 timestamp, which must carry a timezone."""
        _logger.debug(
            "MailDatasetLoader._parse_datetime arguments: value_length=%d",
            len(value),
        )
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise MailDatasetError(f"invalid timestamp {value!r}") from error
