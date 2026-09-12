"""The dialects through which the agent reaches a mail MCP server.

A dialect is the translation between one server's shapes and the mail domain.
It exists because most servers were not written for us: the official Google
server has its own tool names and its own payloads, and a server for Yahoo or
Fastmail would have others again. Rather than teach the skills about each of
them, one class per server implements :class:`MailTools`, and the skills never
find out which one they are talking to.

Adding a server is therefore:

1. a class implementing :class:`MailTools`;
2. a registration here, under a name;
3. a ``config/mcp/<server>.yaml`` declaring ``dialect: <name>``, the transport,
   the capabilities the server really has, and the name it gives to each tool.

Nothing in the domain, the skills or the agent changes.

The ``native`` dialect is the one shortcut we offer: a server implementing
``mail_mcp.protocol`` needs no class at all, because that translation is already
written. It is an offer, never a condition.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from ai_agent_lab.mail.mail_errors import MailToolUnavailableError
from ai_agent_lab.mail.mcp.binding import McpServerBinding
from ai_agent_lab.mail.mcp.connection import McpConnection
from ai_agent_lab.mail.mcp.google.client import GmailMailTools
from ai_agent_lab.mail.mcp.native.client import McpMailTools
from ai_agent_lab.mail.tools_port import MailTools

DialectFactory = Callable[[McpConnection, McpServerBinding, str], MailTools]

NATIVE = "native"
GMAIL = "gmail"
_logger = logging.getLogger(__name__)


def _native(connection: McpConnection, binding: McpServerBinding, owner_id: str) -> MailTools:
    """Build the client of a server implementing the mail protocol."""
    return McpMailTools(connection, binding, owner_id=owner_id)


def _gmail(connection: McpConnection, binding: McpServerBinding, owner_id: str) -> MailTools:
    """Build the client of the official Gmail server."""
    return GmailMailTools(connection, binding, owner_id=owner_id)


class MailDialectRegistry:
    """The dialects this build knows how to speak.

    The registry is explicit rather than discovered: which servers a deployment
    can reach is a decision worth reading in one place, and a typo in a binding
    file should name the alternatives rather than fail deep inside a session.
    """

    def __init__(self, dialects: Mapping[str, DialectFactory] | None = None) -> None:
        _logger.info("Initializing Mail MCP dialect registry")
        _logger.debug(
            "MailDialectRegistry.__init__ arguments: custom_dialects=%s, names=%s",
            dialects is not None,
            tuple(sorted(dialects or {NATIVE: _native, GMAIL: _gmail})),
        )
        self._dialects: dict[str, DialectFactory] = dict(dialects or {NATIVE: _native, GMAIL: _gmail})

    @property
    def known(self) -> tuple[str, ...]:
        """The names this registry answers to, in a stable order."""
        return tuple(sorted(self._dialects))

    def register(self, name: str, factory: DialectFactory) -> None:
        """Add a dialect, refusing to silently replace one."""
        _logger.info("Registering Mail MCP dialect")
        _logger.debug(
            "MailDialectRegistry.register arguments: name=%s, factory_type=%s",
            name,
            type(factory).__name__,
        )
        if name in self._dialects:
            raise MailToolUnavailableError(f"dialect {name!r} is already registered")
        self._dialects[name] = factory

    def build(self, connection: McpConnection, binding: McpServerBinding, owner_id: str) -> MailTools:
        """Build the client a binding asks for."""
        _logger.info("Building Mail MCP dialect client")
        _logger.debug(
            "MailDialectRegistry.build arguments: dialect=%s, server=%s, transport=%s, owner_id=%s, connection_type=%s",
            binding.dialect,
            binding.server,
            binding.transport.value,
            owner_id,
            type(connection).__name__,
        )
        factory = self._dialects.get(binding.dialect)
        if factory is None:
            raise MailToolUnavailableError(
                f"server {binding.server!r} speaks the {binding.dialect!r} dialect, which is not implemented. "
                f"Known dialects: {', '.join(self.known)}."
            )
        return factory(connection, binding, owner_id)
