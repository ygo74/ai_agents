"""Conversation-scoped storage port for prepared drafts."""

from typing import Protocol, runtime_checkable

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.domain.models import MailDraft


@runtime_checkable
class DraftStore(Protocol):
    """Keep exactly the draft a user reviewed, isolated from other users."""

    def put(self, draft: MailDraft, user: UserContext) -> str:
        """Store the prepared draft and return an opaque reference."""
        ...

    def get(self, reference: str, user: UserContext) -> MailDraft:
        """Retrieve the user's draft or raise DraftNotFoundError."""
        ...
