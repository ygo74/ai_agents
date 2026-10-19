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
import logging
from pathlib import Path

from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.bootstrap.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.infrastructure.configuration.environment import MailEnvironmentFile
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentMode, MailAgentSettings
from ai_agent_lab.mail.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.infrastructure.mcp.configuration import load_configuration

_logger = logging.getLogger(__name__)


class MailAuthorisation:
    """Performs the consent handshake and proves the token works."""

    def __init__(self, server: str) -> None:
        _logger.info("Initializing Mail MCP authorisation")
        _logger.debug("MailAuthorisation.__init__ arguments: server=%s", server)
        self._server = server

    async def run(self) -> tuple[int, str]:
        """Authorise, then read the labels to confirm the grant is usable."""
        _logger.info("Running Mail MCP authorisation")
        _logger.debug("MailAuthorisation.run arguments: server=%s", self._server)
        settings = MailAgentSettings(mode=MailAgentMode.MCP)
        provider = MailToolsProvider(
            settings,
            MailDatasetLoader(),
            server=self._server,
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
        return len(labels), _granted_scopes(self._server)


def _granted_scopes(server: str) -> str:
    """Return the scopes the authorisation server actually issued."""
    _logger.info("Reading Mail MCP granted scope metadata")
    _logger.debug("_granted_scopes arguments: none")
    configuration = load_configuration(ConfigurationDirectory.resolve(base_path=Path.cwd()), server)
    if configuration.oauth is None:
        return "not applicable: this server does not use OAuth"
    path = configuration.oauth.token_file
    if not path.is_file():
        return "unknown: no token was stored"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("scope", "not reported"))
    except (OSError, ValueError):
        return "unknown: the token could not be read"


def main() -> None:
    """Entry point of ``python -m ai_agent_lab.mail.adapters.cli.authorise``."""
    _logger.info("Starting Mail MCP authorisation command")
    _logger.debug("main arguments: none")
    parser = argparse.ArgumentParser(description="Authorise the agent against a mail MCP server.")
    parser.add_argument("--server", default="gmail", help="binding name under config/mcp/")
    parser.add_argument("--env-file", type=Path, help="Environment file to load (default: .env).")
    arguments = parser.parse_args()
    server = arguments.server

    MailEnvironmentFile().load(arguments.env_file)
    configuration = load_configuration(ConfigurationDirectory.resolve(base_path=Path.cwd()), server)
    print(f"Authorising against {configuration.binding.server!r} at {configuration.binding.url}")
    if configuration.oauth is not None:
        print(f"Requesting only: {' '.join(configuration.oauth.scopes)}\n")

    label_count, granted = asyncio.run(MailAuthorisation(server).run())

    print(f"\nAuthorisation succeeded. {label_count} labels are readable.")
    print(f"Scopes granted: {granted}")


if __name__ == "__main__":
    main()
