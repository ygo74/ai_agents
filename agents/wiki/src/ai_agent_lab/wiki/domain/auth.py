"""How a caller proves who it is to a wiki.

The scheme is domain vocabulary rather than transport detail: *which identity a
request acts under* is the single most consequential fact about a wiki
integration, because a wiki restricts pages and spaces per person. How that
identity is rendered into an HTTP header belongs to the MCP layer; that there is
one, and whose, belongs here.
"""

from __future__ import annotations

from enum import StrEnum


class WikiAuthScheme(StrEnum):
    """How a caller identifies itself to a wiki MCP server.

    ``NONE`` is not "no security": it means the transport carries no identity of
    its own, either because the server is a local process holding one credential
    or because the protocol passes the caller as a tool argument instead.
    """

    NONE = "none"
    BASIC = "basic"
    # The name of an HTTP authentication scheme, not a credential: it is the
    # literal word the server expects in front of a personal access token.
    TOKEN = "token"  # noqa: S105
    BEARER = "bearer"
