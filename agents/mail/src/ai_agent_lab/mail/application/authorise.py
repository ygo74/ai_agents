"""One-off authorisation against a remote mail MCP server.

Consent happens in a browser and takes as long as a person takes. Letting it
happen inside a tool call means racing that call's deadline, so it is done here
instead: run this once, approve, and every later run uses the stored token.

The command also reports which scopes were actually granted. The Gmail server
asks for far more than the agent needs, so what the token really carries is
worth seeing rather than assuming.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.core.config.environment import EnvironmentFile
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.application.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.config.settings import MailAgentMode, MailAgentSettings, MailMcpSettings
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.mcp.binding import McpServerBindingLoader
from ai_agent_lab.mail.mcp.oauth import MailOAuthSettings

_CONSENT_TIMEOUT_SECONDS = 600


class MailAuthorisation:
    """Performs the consent handshake and proves the token works."""

    def __init__(self, server: str) -> None:
        self._server = server

    async def run(self) -> tuple[int, str]:
        """Authorise, then read the labels to confirm the grant is usable."""
        settings = MailAgentSettings(mode=MailAgentMode.MCP)
        provider = MailToolsProvider(
            settings,
            MailDatasetLoader(),
            mcp_settings=MailMcpSettings(server=self._server, request_timeout_seconds=_CONSENT_TIMEOUT_SECONDS),
        )
        user = UserContext(
            user_id=settings.user_id,
            session_id="authorisation",
            permissions=MailPermission.declared(),
        )
        try:
            labels = await provider.build().list_labels(user)
        finally:
            await provider.aclose()
        return len(labels), _granted_scopes()


def _granted_scopes() -> str:
    """Return the scopes the authorisation server actually issued."""
    path = MailOAuthSettings().token_file
    if not path.is_file():
        return "unknown: no token was stored"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("scope", "not reported"))
    except (OSError, ValueError):
        return "unknown: the token could not be read"


def main() -> None:
    """Entry point of ``python -m ai_agent_lab.mail.application.authorise``."""
    parser = argparse.ArgumentParser(description="Authorise the agent against a mail MCP server.")
    parser.add_argument("--server", default="gmail", help="binding name under config/mcp/")
    server = parser.parse_args().server

    EnvironmentFile().load()
    binding = McpServerBindingLoader(ConfigurationDirectory.resolve(base_path=Path.cwd())).load(server)
    print(f"Authorising against {binding.server!r} at {binding.url}")
    print(f"Requesting only: {MailOAuthSettings().scopes}\n")

    label_count, granted = asyncio.run(MailAuthorisation(server).run())

    print(f"\nAuthorisation succeeded. {label_count} labels are readable.")
    print(f"Scopes granted: {granted}")


if __name__ == "__main__":
    main()
