"""The mail MCP protocol.

This is what a mail MCP server and a mail agent agree on, and nothing more: the
name of each tool, the shape of each payload on the wire, and the code a failure
is reported under.

It deliberately contains no domain model, no security policy and no notion of an
agent. A server implementing it needs to know nothing about who calls it, and an
agent speaking it needs to know nothing about which mailbox is behind it.

Implementing this protocol is a **shortcut, not an entry fee**. A server that
already exists and speaks its own vocabulary - the official Gmail server, a
Yahoo one, a vendor appliance - is reached through a dialect on the agent side
and never sees this package.
"""

from __future__ import annotations

__all__ = ["MailToolName", "errors", "payloads"]

from mail_mcp.protocol import errors, payloads
from mail_mcp.protocol.tools import MailToolName
