"""How a caller identifies itself to a remote wiki MCP server.

A wiki restricts pages and spaces per person, so the single most important
property of a deployment is that the server knows *who is asking*. Over stdio it
cannot: there is one process, one set of credentials, one identity. Over HTTP it
can, and `sooperset/mcp-atlassian` implements exactly that - it reads an
``Authorization`` header on every request and builds a per-user client from it.

This module turns a caller into that header. It is the only place in the wiki
agent that holds a credential, and the value never reaches a prompt, a log, a
``UserContext`` or the domain layer.

Three schemes, matching what the server accepts:

======  =============================================  ====================
Scheme  Header                                         Deployment
======  =============================================  ====================
basic   ``Basic <base64(email:api_token)>``            Confluence Cloud
token   ``Token <personal access token>``              Confluence Data Center
bearer  ``Bearer <oauth access token>``                either, with OAuth
======  =============================================  ====================

``bearer`` is worth a note. The server resolves it to OAuth when it has an OAuth
configuration, and *silently downgrades it to a Data Center PAT when it does
not*. That is convenient and it is also a trap: a deployment that meant OAuth and
forgot to configure it does not fail, it quietly authenticates differently. Say
what you mean with ``token`` when you mean a PAT.
"""

from __future__ import annotations

from base64 import b64encode
from typing import Protocol, runtime_checkable

from pydantic import SecretStr
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.domain.auth import WikiAuthScheme
from ai_agent_lab.wiki.wiki_errors import WikiAccessDeniedError, WikiToolError

AUTHORIZATION = "Authorization"


class WikiAuthorizationError(WikiToolError):
    """Raised when the configured scheme cannot be honoured."""


@runtime_checkable
class WikiUserCredentials(Protocol):
    """Supplies the credential that identifies one caller.

    This is the seam between the proof of concept and a real deployment. Here the
    credential comes from configuration, because there is one local user and no
    identity provider in front. In a deployment serving several people it comes
    from the request - an on-behalf-of token minted for the authenticated caller -
    and only this implementation changes.
    """

    def for_user(self, user: UserContext) -> tuple[str, SecretStr]:
        """Return the account identifier and secret identifying a caller.

        Raises:
            WikiAccessDeniedError: no credential is held for this caller.
        """
        ...


class ConfiguredUserCredentials:
    """Holds the credentials of the users a deployment knows about.

    A caller with no credential is refused rather than served with somebody
    else's. That is the whole point: falling back to a shared account would give
    this person a view of the wiki they are not entitled to, and neither they nor
    the agent would be able to tell.
    """

    def __init__(self, credentials: dict[str, tuple[str, SecretStr]]) -> None:
        self._credentials = dict(credentials)

    def for_user(self, user: UserContext) -> tuple[str, SecretStr]:
        """Return the credential configured for a caller."""
        found = self._credentials.get(user.user_id)
        if found is None:
            raise WikiAccessDeniedError(
                f"no wiki credential is held for {user.user_id!r}, so the wiki cannot be reached as them"
            )
        return found


class WikiAuthorization:
    """Builds the ``Authorization`` header identifying a caller.

    Args:
        scheme: Which header format the bound server expects.
        credentials: Where a caller's credential comes from. Required for every
            scheme but ``none``.
    """

    def __init__(
        self,
        scheme: WikiAuthScheme = WikiAuthScheme.NONE,
        credentials: WikiUserCredentials | None = None,
    ) -> None:
        if scheme is not WikiAuthScheme.NONE and credentials is None:
            raise ValueError(f"the {scheme.value!r} scheme needs a source of user credentials")
        self._scheme = scheme
        self._credentials = credentials

    @property
    def scheme(self) -> WikiAuthScheme:
        """Which header format this builds."""
        return self._scheme

    @property
    def is_per_user(self) -> bool:
        """Whether the server is told who is asking on every request.

        When this is false the connection carries one identity for everybody, and
        the caller must not be allowed to act as somebody else.
        """
        return self._scheme is not WikiAuthScheme.NONE

    def headers_for(self, user: UserContext) -> dict[str, str]:
        """Return the headers identifying a caller, or none at all."""
        if self._credentials is None or self._scheme is WikiAuthScheme.NONE:
            return {}
        account, secret = self._credentials.for_user(user)
        return {AUTHORIZATION: self._value(account, secret)}

    def _value(self, account: str, secret: SecretStr) -> str:
        """Render the header value of the configured scheme.

        ``get_secret_value`` is called here and nowhere else, and the result goes
        straight into a header handed to the transport. It is never stored,
        formatted into a message or returned to a caller.
        """
        if self._scheme is WikiAuthScheme.BASIC:
            encoded = b64encode(f"{account}:{secret.get_secret_value()}".encode()).decode("ascii")
            return f"Basic {encoded}"
        if self._scheme is WikiAuthScheme.TOKEN:
            return f"Token {secret.get_secret_value()}"
        return f"Bearer {secret.get_secret_value()}"

    def __repr__(self) -> str:
        """Redacted representation: never reveals a credential."""
        return f"WikiAuthorization(scheme={self._scheme.value!r}, per_user={self.is_per_user})"


def authorization_for(
    scheme: WikiAuthScheme,
    *,
    user_id: str,
    account: str,
    secret: SecretStr,
) -> WikiAuthorization:
    """Build the authorisation of one configured user.

    A scheme naming no credential is refused here rather than producing an
    unauthenticated request, which the server answers with a 401 much later and
    from somewhere far less obvious.
    """
    if scheme is WikiAuthScheme.NONE:
        return WikiAuthorization()

    if not secret.get_secret_value():
        raise WikiAuthorizationError(f"the {scheme.value!r} scheme also needs a credential (WIKI_MCP_USER_SECRET)")
    if scheme is WikiAuthScheme.BASIC and not account:
        raise WikiAuthorizationError("the 'basic' scheme also needs the account email (WIKI_MCP_USER_ACCOUNT)")

    return WikiAuthorization(scheme, ConfiguredUserCredentials({user_id: (account, secret)}))
