"""Building the identity every operation of one conversation carries.

The authenticated caller and the permissions they are granted are two different
things, and this module is where they meet. `AgentPrincipal` describes who the
identity provider says the caller is; `UserContext` describes what this
application is willing to attempt on their behalf.

They were once joined by a method on the principal. That was the wrong shape: an
identity that knows how to grant itself rights is an identity that can be asked
to grant more, and the runtime's identity model must not depend on the permission
catalogue of whichever application happens to use it.

Permissions are supplied rather than derived, because what a role grants is a
deployment decision. Keeping it here is what lets the same principal be granted
differently by the Mail Agent and by the Wiki Agent.
"""

from __future__ import annotations

from collections.abc import Iterable

from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.security.permissions import Permission
from ygo74.agent_runtime.domains.security.user_context import UserContext


class UserContextFactory:
    """Turns an authenticated caller into the context an operation carries."""

    def for_principal(
        self,
        principal: AgentPrincipal,
        *,
        session_id: str,
        permissions: Iterable[Permission],
    ) -> UserContext:
        """Return the context every operation of one conversation is attributed to."""
        return UserContext(
            user_id=principal.subject,
            session_id=session_id,
            permissions=frozenset(permissions),
        )
