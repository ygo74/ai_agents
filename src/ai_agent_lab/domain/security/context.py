"""Identity carried by every operation that touches protected information."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.domain.security.errors import AuthorizationError


class Permission(StrEnum):
    """Capability a user may hold.

    Permissions are coarse on purpose: fine-grained authorisation belongs to the
    source system, which remains the authority. These values only gate what the
    application is willing to attempt on the user's behalf.
    """

    MAIL_READ = "mail:read"
    MAIL_DRAFT = "mail:draft"
    MAIL_SEND = "mail:send"
    MAIL_MANAGE = "mail:manage"


class UserContext(BaseModel):
    """Who is asking, for the duration of one conversation.

    This object is allowed to reach prompts and logs, therefore it must never
    hold a credential, an OAuth token or a password. Authentication material
    stays in the infrastructure layer, behind the MCP boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    permissions: frozenset[Permission] = frozenset()

    def has_permission(self, permission: Permission) -> bool:
        """Whether the user holds the given permission."""
        return permission in self.permissions

    def require_permission(self, permission: Permission) -> None:
        """Fail fast when the user lacks the given permission."""
        if permission in self.permissions:
            return
        raise AuthorizationError(self.user_id, permission.value)
