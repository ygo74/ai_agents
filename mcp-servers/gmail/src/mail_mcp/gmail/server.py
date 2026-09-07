"""Mail MCP server backed by the Gmail REST API.

It exists because the official Google server is behind the Workspace Developer
Preview Program, which a personal account cannot join, while the REST API it
sits on is generally available.

The Google credential lives in this process and nowhere else: a caller talks MCP
over stdio and never sees a token.
"""

from __future__ import annotations

import argparse

from mail_mcp.gmail.api import GmailApiClient
from mail_mcp.gmail.credentials import GmailCredentials
from mail_mcp.gmail.environment import EnvironmentFile
from mail_mcp.gmail.mailbox import GmailMailbox
from mail_mcp.protocol.serving import MailToolSurface, SingleMailbox

SERVER_NAME = "mail-mcp-gmail"
DEFAULT_OWNER = "local-user"


def build_surface(owner: str) -> MailToolSurface:
    """Assemble the server over a real mailbox.

    The owner is the identifier a caller uses for the person whose mailbox this
    is. The server holds one credential, so it serves exactly one mailbox and
    refuses every other name.
    """
    mailbox = GmailMailbox(GmailApiClient(GmailCredentials()))
    return MailToolSurface(SingleMailbox(owner, mailbox), name=SERVER_NAME)


def main() -> None:
    """Entry point of the ``mail-mcp-gmail`` command."""
    parser = argparse.ArgumentParser(description="Mail MCP server backed by the Gmail REST API.")
    parser.add_argument("--owner", default=DEFAULT_OWNER, help="Identifier of the mailbox owner.")
    arguments = parser.parse_args()

    EnvironmentFile().load()
    build_surface(arguments.owner).run()


if __name__ == "__main__":
    main()
