"""Untrusted content origins declared by the mail domain.

Same discipline as :mod:`ai_agent_lab.mail.domain.permissions`, for the same
reason: an origin is declared by the domain that owns it. A Jira or Confluence
agent declares its own, and nothing here changes - which is exactly what a closed
enumeration in the library made impossible.

An origin is a non-sensitive marker. It says what sort of thing a piece of content
is, never what it contains, so it is safe to log.
"""

from __future__ import annotations

from typing import Final

from ygo74.agent_runtime.domains.security.untrusted import UntrustedOrigin

_DOMAIN: Final = "mail"


class MailOrigin:
    """Where a piece of untrusted mail content came from."""

    SUBJECT: Final = UntrustedOrigin(_DOMAIN, "subject")
    BODY: Final = UntrustedOrigin(_DOMAIN, "body")
    SENDER_NAME: Final = UntrustedOrigin(_DOMAIN, "sender_name")
    ATTACHMENT_NAME: Final = UntrustedOrigin(_DOMAIN, "attachment_name")
    LABEL: Final = UntrustedOrigin(_DOMAIN, "label")

    @classmethod
    def declared(cls) -> frozenset[UntrustedOrigin]:
        """Return every origin the mail domain declares."""
        return frozenset({cls.SUBJECT, cls.BODY, cls.SENDER_NAME, cls.ATTACHMENT_NAME, cls.LABEL})
