"""A wiki MCP server implementing the protocol, over stdio.

Its purpose is not to be a product. It is the reference implementation of the
wiki tool surface: it exposes the ten tools of :mod:`wiki_mcp.protocol`, returns
the protocol payloads, and is backed by a deterministic dataset rather than by
any real documentation system.

That makes two things possible:

- a real MCP client can be exercised over a real protocol stack, with no network,
  no credentials and no Confluence, so a conformance suite runs offline;
- a server built on Confluence, Notion or XWiki has something concrete to match.

Page and space restrictions are deliberately reproduced: a server is the
authority on who may read what, and a double that ignored that would let a client
pass tests it would fail in production.

It serves over stdio by default and over streamable HTTP on request. The HTTP mode
exists so the transport and its three authentication modes can be exercised without
a Confluence instance - and, like every server in this repository, it refuses to
open a port until somebody has said who may reach it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from wiki_mcp.protocol.authentication import WikiMcpAuthentication
from wiki_mcp.protocol.serving import DEFAULT_MCP_PORT, LOOPBACK, Wiki, WikiToolSurface
from wiki_mcp.reference.wiki import WikiDataset, WikiDatasetLoader

DEFAULT_DATASET = Path("data/wiki/sample_wiki.json")
SERVER_NAME = "wiki-mcp-reference"
DEFAULT_HTTP_HOST = "0.0.0.0"  # noqa: S104 - a container serves every interface; the credential is the control
DEFAULT_HTTP_PORT = 9200

STDIO = "stdio"
HTTP = "streamable-http"


class DatasetDirectory:
    """Resolves the wiki one account sees, out of a loaded dataset."""

    def __init__(self, dataset: WikiDataset) -> None:
        self._dataset = dataset

    def resolve(self, account: str) -> Wiki:
        """Return the wiki as this account sees it, never as another one does."""
        return self._dataset.resolve(account)


def build_surface(dataset: Path, *, host: str = LOOPBACK, port: int = DEFAULT_MCP_PORT) -> WikiToolSurface:
    """Assemble the server over a deterministic dataset.

    The bind address is passed in rather than applied later: it decides whether
    DNS-rebinding protection is on, and that cannot be changed after the server is
    built. Loopback is the default, so the stdio path is unaffected.
    """
    return WikiToolSurface(
        DatasetDirectory(WikiDatasetLoader().load(dataset)),
        name=SERVER_NAME,
        host=host,
        port=port,
    )


def main() -> None:
    """Entry point of the ``wiki-mcp-reference`` command."""
    parser = argparse.ArgumentParser(description="Reference wiki MCP server, backed by a JSON dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--transport",
        choices=(STDIO, HTTP),
        default=STDIO,
        help="How callers reach this server. stdio keeps it a child process; streamable-http opens a port.",
    )
    parser.add_argument("--host", default=DEFAULT_HTTP_HOST, help="Interface to bind when serving over HTTP.")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT, help="Port to bind when serving over HTTP.")
    arguments = parser.parse_args()

    if arguments.transport == STDIO:
        build_surface(arguments.dataset).run()
        return

    # Read the authentication *before* building anything, so a server that cannot
    # say who may call it fails at start-up rather than once it is already serving.
    authentication = WikiMcpAuthentication.from_environment()
    build_surface(arguments.dataset, host=arguments.host, port=arguments.port).run_http(authentication)


if __name__ == "__main__":
    main()
