"""Credentials crossing the agent, and the ports that produce them.

Three rules shape this module, and they are security properties rather than
style:

1. A token never enters a :class:`UserContext`, a prompt, a log or a model. It is
   held in :class:`AccessToken`, whose representation is redacted, so an
   accidental ``print`` or f-string cannot leak it.
2. A token received from a caller is never forwarded to a downstream server. The
   MCP specification forbids that passthrough outright and requires a server to
   check that a token was issued for *it*. :class:`DelegatedTokenSource` exists
   so the agent exchanges the token instead of relaying it.
3. Verification produces a :class:`Principal` and nothing else. The rest of the
   application therefore cannot accidentally depend on a claim it has not
   modelled.

Only ports live here. Implementations belong to the infrastructure layer, which
keeps the domain testable without a network and without an identity provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ai_agent_lab.core.security.errors import SecurityError
from ai_agent_lab.core.security.principal import Principal


class TokenError(SecurityError):
    """Base class for failures to verify, exchange or obtain a token."""


class TokenVerificationError(TokenError):
    """Raised when a presented token cannot be trusted.

    Deliberately vague towards the caller: a message distinguishing "expired"
    from "wrong audience" from "bad signature" is a probing oracle. The precise
    reason belongs in the server log.
    """


class TokenExchangeError(TokenError):
    """Raised when a token could not be exchanged for a downstream audience."""


@dataclass(frozen=True, slots=True)
class AccessToken:
    """A bearer credential, kept out of logs by construction.

    The value is only reachable through :meth:`expose`, which makes every place
    that de-references a credential greppable - the same device
    :class:`UntrustedText` uses for third-party content, applied to the opposite
    problem.
    """

    value: str
    audience: str = ""

    def __post_init__(self) -> None:
        """Reject an empty credential rather than carrying a useless one."""
        if not self.value:
            raise ValueError("an access token cannot be empty")

    def expose(self) -> str:
        """Return the raw credential, for a transport that must send it."""
        return self.value

    def __repr__(self) -> str:
        """Redacted representation: never reveals the credential."""
        return f"AccessToken(audience={self.audience!r}, length={len(self.value)})"

    def __str__(self) -> str:
        """Redacted representation, so f-strings cannot leak the credential."""
        return self.__repr__()


@runtime_checkable
class TokenVerifier(Protocol):
    """Establishes who a caller is from a presented bearer token."""

    def verify(self, token: AccessToken) -> Principal:
        """Return the authenticated caller.

        Raises:
            TokenVerificationError: the token was absent, malformed, expired,
                issued by another authority or meant for another audience.
        """
        ...


@runtime_checkable
class DelegatedTokenSource(Protocol):
    """Obtains a token for a downstream service, on behalf of a caller.

    This is what keeps a token scoped to one hop. The mail MCP server must be
    able to check that the token it receives was issued for it, which it cannot
    do if the agent forwards the token LibreChat sent.
    """

    async def token_for(self, principal: Principal, audience: str) -> AccessToken:
        """Return a token the given audience will accept for this principal.

        Raises:
            TokenExchangeError: the authority refused the exchange.
        """
        ...
