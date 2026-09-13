"""Untrusted content origins declared by the wiki domain.

Same discipline as :mod:`ai_agent_lab.wiki.domain.permissions`, for the same
reason: an origin is declared by the domain that owns it. The mail domain declares
its own, and neither knows about the other.

An origin is a non-sensitive marker. It says what sort of thing a piece of content
is, never what it contains, so it is safe to log.
"""

from __future__ import annotations

from typing import Final

from ygo74.agent_runtime.domains.security.untrusted import UntrustedOrigin

_DOMAIN: Final = "wiki"


class WikiOrigin:
    """Where a piece of untrusted wiki content came from."""

    PAGE_TITLE: Final = UntrustedOrigin(_DOMAIN, "page_title")
    PAGE_BODY: Final = UntrustedOrigin(_DOMAIN, "page_body")
    PAGE_EXCERPT: Final = UntrustedOrigin(_DOMAIN, "page_excerpt")
    SPACE_NAME: Final = UntrustedOrigin(_DOMAIN, "space_name")
    COMMENT_BODY: Final = UntrustedOrigin(_DOMAIN, "comment_body")
    AUTHOR_NAME: Final = UntrustedOrigin(_DOMAIN, "author_name")
    LABEL: Final = UntrustedOrigin(_DOMAIN, "label")
    VERSION_MESSAGE: Final = UntrustedOrigin(_DOMAIN, "version_message")

    @classmethod
    def declared(cls) -> frozenset[UntrustedOrigin]:
        """Return every origin the wiki domain declares."""
        return frozenset(
            {
                cls.PAGE_TITLE,
                cls.PAGE_BODY,
                cls.PAGE_EXCERPT,
                cls.SPACE_NAME,
                cls.COMMENT_BODY,
                cls.AUTHOR_NAME,
                cls.LABEL,
                cls.VERSION_MESSAGE,
            }
        )
