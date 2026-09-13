"""The dialects through which the agent reaches a wiki MCP server.

A dialect is the translation between one server's shapes and the wiki domain. It
exists because most servers were not written for us: `sooperset/mcp-atlassian`
has its own tool names and its own payloads, and a Notion or XWiki server would
have others again. Rather than teach the skills about each of them, one class per
server implements :class:`WikiTools`, and the skills never find out which one
they are talking to.

Adding a server is therefore:

1. a class implementing :class:`WikiTools`;
2. a registration here, under a name;
3. a ``config/mcp/<server>.yaml`` declaring ``dialect: <name>``, the transport,
   the capabilities the server really has, and the name it gives to each tool.

Nothing in the domain, the skills or the agent changes.

The ``native`` dialect is the one shortcut we offer: a server implementing
``wiki_mcp.protocol`` needs no class at all, because that translation is already
written. It is an offer, never a condition - and the server this repository
actually targets does not take it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ai_agent_lab.wiki.mcp.atlassian.client import AtlassianWikiTools
from ai_agent_lab.wiki.mcp.binding import McpServerBinding
from ai_agent_lab.wiki.mcp.connection import McpConnection
from ai_agent_lab.wiki.mcp.native.client import McpWikiTools
from ai_agent_lab.wiki.tools_port import WikiTools
from ai_agent_lab.wiki.wiki_errors import WikiToolUnavailableError


@dataclass(frozen=True, slots=True)
class DialectContext:
    """What a dialect needs to know beyond the connection and the binding.

    Attributes:
        account_id: Who a single-identity connection acts for. Only meaningful
            when ``is_per_user`` is false.
        is_per_user: Whether the transport carries the caller's identity on every
            request. True for an HTTP connection sending an ``Authorization``
            header per user; false for a stdio process holding one credential.
    """

    account_id: str = ""
    is_per_user: bool = False


DialectFactory = Callable[[McpConnection, McpServerBinding, DialectContext], WikiTools]

NATIVE = "native"
ATLASSIAN = "atlassian"


def _native(connection: McpConnection, binding: McpServerBinding, context: DialectContext) -> WikiTools:
    """Build the client of a server implementing the wiki protocol.

    The context is not needed here: the protocol carries the caller's identity as
    an argument on every call, so one connection serves everybody and the server
    scopes each answer.
    """
    del context
    return McpWikiTools(connection, binding)


def _atlassian(connection: McpConnection, binding: McpServerBinding, context: DialectContext) -> WikiTools:
    """Build the client of `sooperset/mcp-atlassian`.

    The context matters here. That server takes no account argument: over HTTP it
    resolves the caller from the ``Authorization`` header, and over stdio it acts
    as exactly one person. The dialect needs to know which, so it can refuse to
    serve a second user through a single-identity connection rather than quietly
    returning one person's view of the wiki under another's name.
    """
    return AtlassianWikiTools(
        connection,
        binding,
        account_id=context.account_id,
        is_per_user=context.is_per_user,
    )


class WikiDialectRegistry:
    """The dialects this build knows how to speak.

    The registry is explicit rather than discovered: which servers a deployment
    can reach is a decision worth reading in one place, and a typo in a binding
    file should name the alternatives rather than fail deep inside a session.
    """

    def __init__(self, dialects: Mapping[str, DialectFactory] | None = None) -> None:
        self._dialects: dict[str, DialectFactory] = dict(dialects or {NATIVE: _native, ATLASSIAN: _atlassian})

    @property
    def known(self) -> tuple[str, ...]:
        """The names this registry answers to, in a stable order."""
        return tuple(sorted(self._dialects))

    def register(self, name: str, factory: DialectFactory) -> None:
        """Add a dialect, refusing to silently replace one."""
        if name in self._dialects:
            raise WikiToolUnavailableError(f"dialect {name!r} is already registered")
        self._dialects[name] = factory

    def build(
        self,
        connection: McpConnection,
        binding: McpServerBinding,
        context: DialectContext | None = None,
    ) -> WikiTools:
        """Build the client a binding asks for."""
        factory = self._dialects.get(binding.dialect)
        if factory is None:
            raise WikiToolUnavailableError(
                f"server {binding.server!r} speaks the {binding.dialect!r} dialect, which is not "
                f"implemented. Known dialects: {', '.join(self.known)}."
            )
        return factory(connection, binding, context or DialectContext())
