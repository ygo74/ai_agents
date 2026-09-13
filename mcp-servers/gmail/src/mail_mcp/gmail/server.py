"""Mail MCP server backed by the Gmail REST API.

It exists because the official Google server is behind the Workspace Developer
Preview Program, which a personal account cannot join, while the REST API it
sits on is generally available.

The Google credential lives in this process and nowhere else. Over stdio that is
the whole story: a caller talks MCP through a pipe and never sees a token.

Over HTTP there is a second half, and it is why ``--transport`` is not merely a
convenience. A port is reachable by anything on the network, so the HTTP surface
authenticates its caller and refuses to start without a token to check. See
:mod:`mail_mcp.protocol.http_surface`.

The initial Google consent is interactive - it opens a browser and listens on the
loopback interface - so it cannot happen inside a container. Run
``mail-mcp-gmail-authorise`` on a workstation and mount the token file.
"""

from __future__ import annotations

import argparse

from mail_mcp.gmail.api import GmailApiClient
from mail_mcp.gmail.credentials import GmailCredentials
from mail_mcp.gmail.environment import EnvironmentFile
from mail_mcp.gmail.mailbox import GmailMailbox
from mail_mcp.protocol.http_surface import required_token
from mail_mcp.protocol.serving import DEFAULT_MCP_PORT, LOOPBACK, MailToolSurface, SingleMailbox

SERVER_NAME = "mail-mcp-gmail"
DEFAULT_OWNER = "local-user"
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - a container serves every interface; the token is the control
DEFAULT_PORT = 9100

STDIO = "stdio"
HTTP = "streamable-http"


def build_surface(owner: str, *, host: str = LOOPBACK, port: int = DEFAULT_MCP_PORT) -> MailToolSurface:
    """Assemble the server over a real mailbox.

    The owner is the identifier a caller uses for the person whose mailbox this
    is. The server holds one credential, so it serves exactly one mailbox and
    refuses every other name.

    The bind address is passed in rather than applied later: it decides whether
    DNS-rebinding protection is on, and that cannot be changed after the server
    is built. Loopback is the default, so the stdio path is unaffected.
    """
    mailbox = GmailMailbox(GmailApiClient(GmailCredentials()))
    return MailToolSurface(SingleMailbox(owner, mailbox), name=SERVER_NAME, host=host, port=port)


def main() -> None:
    """Entry point of the ``mail-mcp-gmail`` command."""
    parser = argparse.ArgumentParser(description="Mail MCP server backed by the Gmail REST API.")
    parser.add_argument("--owner", default=DEFAULT_OWNER, help="Identifier of the mailbox owner.")
    parser.add_argument(
        "--transport",
        choices=(STDIO, HTTP),
        default=STDIO,
        help="How callers reach this server. stdio keeps it a child process; streamable-http opens a port.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Interface to bind when serving over HTTP.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind when serving over HTTP.")
    arguments = parser.parse_args()

    EnvironmentFile().load()

    if arguments.transport == STDIO:
        build_surface(arguments.owner).run()
        return

    # Read the token *before* building anything: a missing one must fail at
    # start-up, not after the mailbox client is already holding a credential.
    token = required_token()
    surface = build_surface(arguments.owner, host=arguments.host, port=arguments.port)
    surface.run_http(token=token)


if __name__ == "__main__":
    main()
