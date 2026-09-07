"""Discovery of what a mail MCP server actually exposes.

Response shapes are not part of the MCP specification, and Google does not
publish theirs. Guessing them would mean writing a mapping against an
assumption, so this command asks the server instead: it connects, lists the
tools, and records their real schemas.

The recording is what the Gmail dialect is then written against, and what a
future change to the server is compared to.

Nothing is executed against the mailbox: the discovery only lists tools. Reading
a message is a separate, explicit step.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession

from ai_agent_lab.infrastructure.config.directory import ConfigurationDirectory
from ai_agent_lab.infrastructure.config.mcp_binding import McpServerBinding, McpServerBindingLoader
from ai_agent_lab.infrastructure.config.settings import ENV_FILE, McpTransport
from ai_agent_lab.infrastructure.mcp.connection import McpConnection
from ai_agent_lab.infrastructure.mcp.oauth import MailOAuthProvider

DEFAULT_OUTPUT = Path("docs/mcp-discovery")


class ToolDiscovery:
    """Lists the tools a server exposes and records their schemas."""

    def __init__(self, binding: McpServerBinding) -> None:
        self._binding = binding

    async def run(self) -> dict[str, Any]:
        """Connect, list the tools, and return what the server declared."""
        connection = McpConnection(self._binding, auth=self._auth())
        try:
            session = await connection.session()
            return await self._describe(session)
        finally:
            await connection.aclose()

    def _auth(self) -> Any:
        """Build the authentication a remote server requires."""
        if self._binding.transport is not McpTransport.HTTP:
            return None
        return MailOAuthProvider().build(self._binding.url)

    async def _describe(self, session: ClientSession) -> dict[str, Any]:
        """Collect the declared tools of an open session."""
        listing = await session.list_tools()
        return {
            "server": self._binding.server,
            "transport": self._binding.transport.value,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                    "output_schema": tool.outputSchema,
                    "annotations": None if tool.annotations is None else tool.annotations.model_dump(),
                }
                for tool in sorted(listing.tools, key=lambda item: item.name)
            ],
        }


def main() -> None:
    """Entry point of ``python -m ai_agent_lab.infrastructure.mcp.discover``."""
    parser = argparse.ArgumentParser(description="Record what a mail MCP server exposes.")
    parser.add_argument("--server", default="gmail", help="binding name under config/mcp/")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    _load_environment()
    binding = McpServerBindingLoader(ConfigurationDirectory.resolve()).load(arguments.server)
    discovered = asyncio.run(ToolDiscovery(binding).run())

    arguments.output.mkdir(parents=True, exist_ok=True)
    destination = arguments.output / f"{arguments.server}-tools.json"
    destination.write_text(json.dumps(discovered, indent=2, sort_keys=True), encoding="utf-8")

    print(f"\n{len(discovered['tools'])} tools recorded in {destination}")
    for tool in discovered["tools"]:
        structured = "structured" if tool["output_schema"] else "unstructured"
        print(f"  - {tool['name']} ({structured})")


def _load_environment() -> None:
    """Make the delivered configuration visible before anything reads it."""
    from ai_agent_lab.infrastructure.config.environment import EnvironmentFile

    EnvironmentFile(Path(ENV_FILE)).load()


if __name__ == "__main__":
    main()
