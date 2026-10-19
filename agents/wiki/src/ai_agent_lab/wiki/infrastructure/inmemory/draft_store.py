"""In-memory store of the page drafts prepared during a conversation."""

from __future__ import annotations

import uuid

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.domain.errors import WikiDraftNotFoundError
from ai_agent_lab.wiki.domain.models import WikiPageDraft


class InMemoryWikiDraftStore:
    """Keeps prepared page drafts for the lifetime of a process.

    References are opaque and scoped to their author, so one person cannot
    redeem a reference issued to another and write their content to the wiki.
    """

    def __init__(self) -> None:
        self._drafts: dict[tuple[str, str], WikiPageDraft] = {}

    def put(self, draft: WikiPageDraft, user: UserContext) -> str:
        """Store a draft and return the reference identifying it."""
        reference = f"wiki-draft-{uuid.uuid4().hex[:12]}"
        self._drafts[(user.user_id, reference)] = draft
        return reference

    def get(self, reference: str, user: UserContext) -> WikiPageDraft:
        """Return a previously stored draft."""
        draft = self._drafts.get((user.user_id, reference))
        if draft is None:
            raise WikiDraftNotFoundError(reference)
        return draft
