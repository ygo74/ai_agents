"""Who the agent is acting for, established outside the application.

Until now a single user was named in ``.env``. Serving several people over HTTP
makes that impossible: the caller is whoever the transport authenticated, and the
application must be told, not configured.

A :class:`Principal` is the result of that authentication - a subject, a mailbox
address, a display name and the roles the identity provider asserted. It is
deliberately *not* a token: it carries no credential, so it may reach a log, an
audit record or a prompt without leaking anything. Authentication material stays
in the infrastructure layer, exactly as :class:`UserContext` already requires.

The translation from a wire-shaped authentication context lives here rather than
in the transport, so a change of serving library touches one method instead of
every entry point.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.errors import SecurityError
from ai_agent_lab.core.security.permissions import Permission

_IDENTITY: Final = "identity"
_SUBJECT: Final = "subject"
_USER_ID: Final = "userId"
_EMAIL: Final = "email"
_NAME: Final = "name"
_USERNAME: Final = "username"
_ROLES: Final = "roles"


class PrincipalError(SecurityError):
    """Raised when an authenticated caller cannot be turned into a principal.

    Failing here is a refusal to serve, never a fallback to an anonymous or
    default identity: acting for "somebody" is how one mailbox ends up answering
    for another.
    """


class Principal(BaseModel):
    """An authenticated caller, without any credential.

    Attributes:
        subject: Stable identifier of the person, as asserted by the identity
            provider. This is what every mailbox, ledger and audit entry is
            partitioned by, so it must never be derived from client-supplied
            data.
        email: Address of the person, when the identity provider asserts one.
            Optional because it is an attribute of an identity rather than a
            requirement of every agent: a mailbox is addressed by email, a wiki
            account is not. An agent that needs one says so itself, and fails
            loudly when it is absent, rather than this model demanding it of
            agents that do not.
        display_name: Human-readable name, for prompts and confirmations.
        roles: Roles asserted by the identity provider. They are claims about
            the caller, not permissions: mapping them to permissions is a
            decision of the application.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    email: str = ""
    display_name: str = ""
    roles: frozenset[str] = frozenset()

    @classmethod
    def from_auth_context(cls, context: Mapping[str, object] | None) -> Principal:
        """Build a principal from a wire-shaped authentication context.

        The mapping is the shape a serving library hands to an application:
        loosely typed by nature, because it crosses a transport boundary. This
        is the single place allowed to read it, so the rest of the application
        keeps working with a typed model - the same discipline applied to MCP
        payloads.
        """
        if not context:
            raise PrincipalError("the request carried no authenticated caller")

        identity = context.get(_IDENTITY)
        identity_map: Mapping[str, object] = identity if isinstance(identity, Mapping) else {}

        subject = _text(identity_map.get(_SUBJECT)) or _text(identity_map.get(_USER_ID)) or _text(context.get(_USER_ID))
        if not subject:
            raise PrincipalError("the authenticated caller carries no subject")

        email = _text(identity_map.get(_EMAIL))
        if not email:
            raise PrincipalError(f"the authenticated caller {subject!r} carries no email address")

        return cls(
            subject=subject,
            email=email,
            display_name=_text(identity_map.get(_NAME)) or _text(identity_map.get(_USERNAME)),
            roles=_texts(context.get(_ROLES)),
        )

    def has_role(self, role: str) -> bool:
        """Whether the identity provider asserted a role for this caller."""
        return role in self.roles

    def to_user_context(self, *, session_id: str, permissions: Iterable[Permission]) -> UserContext:
        """Build the identity every operation of one conversation carries.

        Permissions are supplied rather than derived: what a role grants is a
        deployment decision, and keeping it out of this model is what lets the
        same principal be granted differently by two agents.
        """
        return UserContext(
            user_id=self.subject,
            session_id=session_id,
            permissions=frozenset(permissions),
        )


def _text(value: object) -> str:
    """Return a non-empty string, or nothing at all."""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _texts(value: object) -> frozenset[str]:
    """Return the non-empty strings of a wire-shaped list, ignoring the rest."""
    if not isinstance(value, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(text for item in value if (text := _text(item)))
