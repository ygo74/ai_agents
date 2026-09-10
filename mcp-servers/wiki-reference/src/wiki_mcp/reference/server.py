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
"""

from __future__ import annotations

import argparse
from pathlib import Path

from wiki_mcp.protocol.serving import Wiki, WikiToolSurface
from wiki_mcp.reference.wiki import WikiDataset, WikiDatasetLoader

DEFAULT_DATASET = Path("data/wiki/sample_wiki.json")
SERVER_NAME = "wiki-mcp-reference"


class DatasetDirectory:
    """Resolves the wiki one account sees, out of a loaded dataset."""

    def __init__(self, dataset: WikiDataset) -> None:
        self._dataset = dataset

    def resolve(self, account: str) -> Wiki:
        """Return the wiki as this account sees it, never as another one does."""
        return self._dataset.resolve(account)


def build_surface(dataset: Path) -> WikiToolSurface:
    """Assemble the server over a deterministic dataset."""
    return WikiToolSurface(DatasetDirectory(WikiDatasetLoader().load(dataset)), name=SERVER_NAME)


def main() -> None:
    """Entry point of the ``wiki-mcp-reference`` command."""
    parser = argparse.ArgumentParser(description="Reference wiki MCP server, backed by a JSON dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    arguments = parser.parse_args()

    build_surface(arguments.dataset).run()


if __name__ == "__main__":
    main()
