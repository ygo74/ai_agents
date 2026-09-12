"""In-memory store of the drafts prepared during a conversation."""

from __future__ import annotations

import logging
import uuid

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.domain.errors import DraftNotFoundError
from ai_agent_lab.mail.domain.models import MailDraft

_logger = logging.getLogger(__name__)


class InMemoryDraftStore:
    """Keeps prepared drafts for the lifetime of a process.

    References are opaque and scoped to their owner, so one user cannot redeem
    a reference issued for another mailbox.
    """

    def __init__(self) -> None:
        _logger.info("Initializing in-memory Mail draft store")
        _logger.debug("InMemoryDraftStore.__init__ arguments: none")
        self._drafts: dict[tuple[str, str], MailDraft] = {}

    def put(self, draft: MailDraft, user: UserContext) -> str:
        """Store a draft and return the reference identifying it."""
        _logger.info("Storing Mail draft reference")
        _logger.debug(
            "InMemoryDraftStore.put arguments: user_id=%s, to_count=%d, cc_count=%d, subject_length=%d, body_length=%d",
            user.user_id,
            len(draft.to),
            len(draft.cc),
            len(draft.subject.expose()),
            len(draft.body.expose()),
        )
        reference = f"draft-{uuid.uuid4().hex[:12]}"
        self._drafts[(user.user_id, reference)] = draft
        return reference

    def get(self, reference: str, user: UserContext) -> MailDraft:
        """Return a previously stored draft."""
        _logger.info("Reading Mail draft reference")
        _logger.debug(
            "InMemoryDraftStore.get arguments: reference=%s, user_id=%s",
            reference,
            user.user_id,
        )
        draft = self._drafts.get((user.user_id, reference))
        if draft is None:
            raise DraftNotFoundError(reference)
        return draft
