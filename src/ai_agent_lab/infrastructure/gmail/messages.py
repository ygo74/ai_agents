"""Translation of Gmail resources into domain models.

A Gmail message is a MIME tree with headers in a list and bodies encoded in
URL-safe base64. Turning that into a typed message is deterministic work, so it
lives in code and is tested on its own.

Read state and archiving are not fields: Gmail expresses them as the ``UNREAD``
and ``INBOX`` labels, and they are read back the same way they are written.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from ai_agent_lab.domain.mail.models import (
    EmailAddress,
    MailAttachment,
    MailLabel,
    MailMessage,
    MailParticipant,
)
from ai_agent_lab.domain.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.mcp.mail.errors import MailToolProtocolError

UNREAD_LABEL = "UNREAD"
INBOX_LABEL = "INBOX"

_TEXT_PLAIN = "text/plain"
_SYSTEM_LABEL = "system"


class GmailMessageReader:
    """Reads one Gmail message resource."""

    def to_domain(self, resource: dict[str, Any]) -> MailMessage:
        """Rebuild a typed message, fencing every piece of free text."""
        headers = _Headers(resource.get("payload") or {})
        message_id = str(resource.get("id", ""))
        if not message_id:
            raise MailToolProtocolError("Gmail returned a message without an identifier")
        label_ids = tuple(str(item) for item in resource.get("labelIds") or ())
        return MailMessage(
            message_id=message_id,
            thread_id=str(resource.get("threadId", message_id)),
            subject=untrusted(headers.single("Subject"), UntrustedOrigin.MAIL_SUBJECT),
            body=untrusted(self._body(resource), UntrustedOrigin.MAIL_BODY),
            sender=_participant(headers.single("From")),
            to=tuple(_participant(item) for item in headers.addresses("To")),
            cc=tuple(_participant(item) for item in headers.addresses("Cc")),
            sent_at=self._sent_at(resource, headers),
            is_read=UNREAD_LABEL not in label_ids,
            is_archived=INBOX_LABEL not in label_ids,
            label_ids=label_ids,
            attachments=tuple(self._attachments(resource.get("payload") or {})),
        )

    def _body(self, resource: dict[str, Any]) -> str:
        """Return the plain-text body, falling back to the snippet."""
        for part in _walk(resource.get("payload") or {}):
            if part.get("mimeType") == _TEXT_PLAIN:
                decoded = _decode((part.get("body") or {}).get("data", ""))
                if decoded:
                    return decoded
        return str(resource.get("snippet", ""))

    def _attachments(self, payload: dict[str, Any]) -> Iterator[MailAttachment]:
        """Yield the attachment metadata, never the bytes."""
        for part in _walk(payload):
            filename = str(part.get("filename", ""))
            body = part.get("body") or {}
            if not filename or not body.get("attachmentId"):
                continue
            yield MailAttachment(
                attachment_id=str(body["attachmentId"]),
                file_name=untrusted(filename, UntrustedOrigin.MAIL_ATTACHMENT_NAME),
                media_type=str(part.get("mimeType", "application/octet-stream")),
                size_bytes=int(body.get("size", 0)),
            )

    @staticmethod
    def _sent_at(resource: dict[str, Any], headers: _Headers) -> datetime:
        """Return when the message was sent.

        ``internalDate`` is Gmail's own timestamp and is always present; the
        ``Date`` header is written by the sender and is therefore only a
        fallback.
        """
        internal = resource.get("internalDate")
        if internal is not None:
            return datetime.fromtimestamp(int(internal) / 1000, tz=UTC)
        raw = headers.single("Date")
        if not raw:
            raise MailToolProtocolError("Gmail returned a message without a date")
        try:
            return parsedate_to_datetime(raw).astimezone(UTC)
        except (TypeError, ValueError) as error:
            raise MailToolProtocolError("Gmail returned a message with an unreadable date") from error


class GmailLabelReader:
    """Reads Gmail label resources."""

    def to_domain(self, resource: dict[str, Any]) -> MailLabel:
        """Rebuild a typed label, fencing its name."""
        return MailLabel(
            label_id=str(resource.get("id", "")),
            name=untrusted(str(resource.get("name", "")), UntrustedOrigin.MAIL_LABEL),
            is_system=str(resource.get("type", "")).lower() == _SYSTEM_LABEL,
        )


class _Headers:
    """The header list of a Gmail payload, addressed by name."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._by_name = {
            str(header.get("name", "")).lower(): str(header.get("value", ""))
            for header in payload.get("headers") or ()
        }

    def single(self, name: str) -> str:
        """Return one header value, empty when absent."""
        return self._by_name.get(name.lower(), "")

    def addresses(self, name: str) -> tuple[str, ...]:
        """Return the addresses of a comma-separated header."""
        raw = self.single(name)
        return tuple(part.strip() for part in raw.split(",") if part.strip())


def _participant(value: str) -> MailParticipant:
    """Read a participant out of an address header."""
    name, address = parseaddr(value)
    return MailParticipant(
        address=EmailAddress(value=address or value.strip()),
        display_name=untrusted(name, UntrustedOrigin.MAIL_SENDER_NAME) if name else None,
    )


def _walk(part: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield a MIME part and everything nested inside it."""
    yield part
    for child in part.get("parts") or ():
        yield from _walk(child)


def _decode(data: str) -> str:
    """Decode a URL-safe base64 body, tolerating missing padding."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return ""
