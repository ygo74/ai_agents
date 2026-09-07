"""A mail MCP server implementing the protocol, over stdio.

Its purpose is not to be a product. It is the reference implementation of the
mail tool surface: it exposes the twelve tools of :mod:`mail_mcp.protocol`, returns
the protocol payloads, and is backed by a deterministic dataset rather than by
any real mail system.

That makes two things possible:

- a real MCP client can be exercised over a real protocol stack, with no network,
  no credentials and no mailbox, so a conformance suite runs offline;
- a server built on EWS or Microsoft Graph has something concrete to match. If it
  answers these twelve tools with these payloads, a caller works against it without
  a single line of adaptation.

Mailbox isolation is deliberately reproduced: a server is the authority on who
may read a mailbox, and a double that ignored that would let a client pass tests
it would fail in production.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mail_mcp.protocol.serving import Mailbox, MailToolSurface
from mail_mcp.reference.mailbox import MailboxDataset, MailboxDatasetLoader

DEFAULT_DATASET = Path("data/mail/sample_mailbox.json")
SERVER_NAME = "mail-mcp-reference"


class DatasetDirectory:
    """Resolves a mailbox out of a loaded dataset."""

    def __init__(self, dataset: MailboxDataset) -> None:
        self._dataset = dataset

    def resolve(self, owner: str) -> Mailbox:
        """Return the mailbox of an owner, never another one's."""
        return self._dataset.resolve(owner)


def build_surface(dataset: Path) -> MailToolSurface:
    """Assemble the server over a deterministic dataset."""
    return MailToolSurface(DatasetDirectory(MailboxDatasetLoader().load(dataset)), name=SERVER_NAME)


def main() -> None:
    """Entry point of the ``mail-mcp-reference`` command."""
    parser = argparse.ArgumentParser(description="Reference mail MCP server, backed by a JSON dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    arguments = parser.parse_args()

    build_surface(arguments.dataset).run()


if __name__ == "__main__":
    main()
