"""Translation of Gmail resources into protocol payloads.

A Gmail message is a MIME tree with headers in a list and bodies encoded in
URL-safe base64. Turning that into a wire message is deterministic work, so it
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

from mail_mcp.protocol import payloads as wire
from mail_mcp.protocol.errors import ProtocolError

UNREAD_LABEL = "UNREAD"
INBOX_LABEL = "INBOX"

_TEXT_PLAIN = "text/plain"
_SYSTEM_LABEL = "system"


class GmailMessageReader:
    """Reads one Gmail message resource into a wire message."""

    def to_wire(self, resource: dict[str, Any]) -> wire.Message:
        """Rebuild a wire message from a Gmail resource."""
        headers = _Headers(resource.get("payload") or {})
        message_id = str(resource.get("id", ""))
        if not message_id:
            raise ProtocolError("Gmail returned a message without an identifier")
        label_ids = tuple(str(item) for item in resource.get("labelIds") or ())
        return wire.Message(
            message_id=message_id,
            thread_id=str(resource.get("threadId", message_id)),
            subject=headers.single("Subject"),
            body=self._body(resource),
            sender=_participant(headers.single("From")),
            to=tuple(_participant(item) for item in headers.addresses("To")),
            cc=tuple(_participant(item) for item in headers.addresses("Cc")),
            sent_at=self._sent_at(resource, headers, message_id),
            is_read=UNREAD_LABEL not in label_ids,
            is_archived=INBOX_LABEL not in label_ids,
            label_ids=label_ids,
            attachments=tuple(self._attachments(resource.get("payload") or {})),
        )

    def to_header(self, resource: dict[str, Any]) -> wire.Header:
        """Project a Gmail resource onto a search hit, without its body."""
        message = self.to_wire(resource)
        return wire.Header(
            message_id=message.message_id,
            thread_id=message.thread_id,
            subject=message.subject,
            sender=message.sender,
            recipient_count=len(message.to) + len(message.cc),
            sent_at=message.sent_at,
            is_read=message.is_read,
            is_archived=message.is_archived,
            has_attachments=bool(message.attachments or resource.get("attachmentIds")),
            label_ids=message.label_ids,
        )

    def _body(self, resource: dict[str, Any]) -> str:
        """Return the plain-text body, falling back to the snippet."""
        for part in _walk(resource.get("payload") or {}):
            if part.get("mimeType") == _TEXT_PLAIN:
                decoded = _decode((part.get("body") or {}).get("data", ""))
                if decoded:
                    return decoded
        return str(resource.get("snippet", ""))

    def _attachments(self, payload: dict[str, Any]) -> Iterator[wire.Attachment]:
        """Yield the attachment metadata, never the bytes."""
        for part in _walk(payload):
            filename = str(part.get("filename", ""))
            body = part.get("body") or {}
            if not filename or not body.get("attachmentId"):
                continue
            yield wire.Attachment(
                attachment_id=str(body["attachmentId"]),
                file_name=filename,
                media_type=str(part.get("mimeType", "application/octet-stream")),
                size_bytes=int(body.get("size", 0)),
            )

    @staticmethod
    def _sent_at(resource: dict[str, Any], headers: _Headers, message_id: str) -> datetime:
        """Return when the message was sent.

        ``internalDate`` is Gmail's own timestamp and is always present; the
        ``Date`` header is written by the sender and is only a fallback.
        """
        internal = resource.get("internalDate")
        if internal is not None:
            return datetime.fromtimestamp(int(internal) / 1000, tz=UTC)
        raw = headers.single("Date")
        if not raw:
            raise ProtocolError(f"message {message_id!r} was returned without a date")
        try:
            return parsedate_to_datetime(raw).astimezone(UTC)
        except (TypeError, ValueError) as error:
            raise ProtocolError(f"message {message_id!r} has an unreadable date") from error


class GmailLabelReader:
    """Reads Gmail label resources into wire labels."""

    def to_wire(self, resource: dict[str, Any]) -> wire.Label:
        """Rebuild a wire label from a Gmail resource."""
        return wire.Label(
            label_id=str(resource.get("id", "")),
            name=str(resource.get("name", "")),
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


def _participant(value: str) -> wire.Participant:
    """Read a participant out of an address header."""
    name, address = parseaddr(value)
    return wire.Participant(address=address or value.strip(), display_name=name or None)


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
