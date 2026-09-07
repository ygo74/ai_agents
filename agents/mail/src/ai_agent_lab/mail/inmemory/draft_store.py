"""In-memory store of the drafts prepared during a conversation."""

from __future__ import annotations

import uuid

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.errors import DraftNotFoundError
from ai_agent_lab.mail.domain.models import MailDraft


class InMemoryDraftStore:
    """Keeps prepared drafts for the lifetime of a process.

    References are opaque and scoped to their owner, so one user cannot redeem
    a reference issued for another mailbox.
    """

    def __init__(self) -> None:
        self._drafts: dict[tuple[str, str], MailDraft] = {}

    def put(self, draft: MailDraft, user: UserContext) -> str:
        """Store a draft and return the reference identifying it."""
        reference = f"draft-{uuid.uuid4().hex[:12]}"
        self._drafts[(user.user_id, reference)] = draft
        return reference

    def get(self, reference: str, user: UserContext) -> MailDraft:
        """Return a previously stored draft."""
        draft = self._drafts.get((user.user_id, reference))
        if draft is None:
            raise DraftNotFoundError(reference)
        return draft
