"""Untrusted content primitives.

Anything returned by an MCP server - mail bodies, subjects, sender names,
Jira descriptions, Confluence pages, web content - is data produced by a third
party. It must never be interpreted as an instruction.

:class:`UntrustedText` makes that property explicit in the type system. The raw
value can only be obtained through :meth:`UntrustedText.expose`, which makes
every place that de-references untrusted content greppable and reviewable.
Its ``repr`` deliberately hides the value so accidental logging cannot leak
message content.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UntrustedOrigin(StrEnum):
    """Non-sensitive marker describing where untrusted content came from."""

    MAIL_SUBJECT = "mail_subject"
    MAIL_BODY = "mail_body"
    MAIL_SENDER_NAME = "mail_sender_name"
    MAIL_ATTACHMENT_NAME = "mail_attachment_name"
    MAIL_LABEL = "mail_label"

    WIKI_PAGE_TITLE = "wiki_page_title"
    WIKI_PAGE_BODY = "wiki_page_body"
    WIKI_PAGE_EXCERPT = "wiki_page_excerpt"
    WIKI_SPACE_NAME = "wiki_space_name"
    WIKI_COMMENT_BODY = "wiki_comment_body"
    WIKI_AUTHOR_NAME = "wiki_author_name"
    WIKI_LABEL = "wiki_label"
    WIKI_VERSION_MESSAGE = "wiki_version_message"


class UntrustedText(BaseModel):
    """Text produced outside the trust boundary of the application.

    The payload is excluded from ``repr``/``str`` so that logging a model that
    embeds untrusted content cannot leak it. Read the payload through
    :meth:`expose`, which documents the caller's intent at the call site.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: UntrustedOrigin
    payload: str = Field(repr=False)

    @property
    def length(self) -> int:
        """Length of the underlying text, safe to log."""
        return len(self.payload)

    @property
    def is_empty(self) -> bool:
        """Whether the underlying text holds no visible character."""
        return not self.payload.strip()

    def expose(self) -> str:
        """Return the raw untrusted text.

        Callers must treat the result as data. It may only be embedded in a
        prompt through a builder that delimits and labels untrusted sections.
        """
        return self.payload

    def __repr__(self) -> str:
        """Redacted representation: never reveals the untrusted payload."""
        return f"UntrustedText(origin={self.origin.value!r}, length={self.length})"

    def __str__(self) -> str:
        """Redacted representation, so f-strings cannot leak the payload."""
        return self.__repr__()


def untrusted(value: str, origin: UntrustedOrigin) -> UntrustedText:
    """Wrap a raw string coming from outside the trust boundary."""
    return UntrustedText(origin=origin, payload=value)
