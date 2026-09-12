"""Ports the wiki domain needs from the surrounding application."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.domain.models import WikiPageDraft


@runtime_checkable
class WikiDraftStore(Protocol):
    """Holds the page drafts prepared during a conversation.

    Composing a page and writing it are two separate turns. Keeping the prepared
    content on the application side, and exchanging only an opaque reference,
    means what reaches the wiki is exactly what the user approved: a model cannot
    quietly rewrite the body between the moment it is shown and the moment it is
    written.

    That property is the reason the LangGraph ``edit`` decision is refused
    elsewhere in this agent. Both guards protect the same thing.

    Every operation is scoped to a user, so a reference issued for one person can
    never be redeemed by another.
    """

    def put(self, draft: WikiPageDraft, user: UserContext) -> str:
        """Store a draft and return the reference identifying it."""
        ...

    def get(self, reference: str, user: UserContext) -> WikiPageDraft:
        """Return a previously stored draft.

        Raises:
            WikiDraftNotFoundError: unknown reference for this user.
        """
        ...
