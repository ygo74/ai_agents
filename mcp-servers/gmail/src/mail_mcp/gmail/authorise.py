"""One-off consent for the Gmail API.

Consent is done here rather than inside the MCP server, because that server runs
as a subprocess whose output the client does not show: the browser would open
with nobody told why. Run this once, approve, and the server refreshes the grant
on its own from then on.

The command finishes by reading the labels, so a grant that cannot actually be
used is reported now rather than during a conversation.
"""

from __future__ import annotations

import asyncio

from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.infrastructure.config.environment import EnvironmentFile
from ai_agent_lab.infrastructure.gmail.api import GmailApiClient
from ai_agent_lab.infrastructure.gmail.credentials import GmailCredentials, GmailCredentialSettings
from ai_agent_lab.infrastructure.gmail.mail_tools import GmailApiMailTools
from ai_agent_lab.infrastructure.oauth.loopback import LoopbackConsent

# The Gmail API acts for the account that consented, so the caller identity is
# not part of a request. The mailbox owner is enforced by the MCP client.
_CONSENTING_ACCOUNT = UserContext(user_id="gmail", session_id="authorisation")


class GmailConsent:
    """Obtains a grant and proves it works."""

    def __init__(self, credentials: GmailCredentials) -> None:
        self._credentials = credentials

    async def run(self) -> tuple[int, str]:
        """Authorise, then read the labels back."""
        await self._credentials.authorise()
        tools = GmailApiMailTools(GmailApiClient(self._credentials))
        labels = await tools.list_labels(_CONSENTING_ACCOUNT)
        return len(labels), self._credentials.granted_scopes()


def main() -> None:
    """Entry point of ``python -m ai_agent_lab.infrastructure.gmail.authorise``."""
    EnvironmentFile().load()
    settings = GmailCredentialSettings()
    settings.require_client()

    print(f"Redirect URI: {LoopbackConsent(settings.callback_port).redirect_uri}")
    print("Requesting:")
    for scope in settings.scopes.split():
        print(f"  - {scope}")

    label_count, granted = asyncio.run(GmailConsent(GmailCredentials(settings)).run())

    print(f"\nAuthorisation succeeded. {label_count} labels are readable.")
    print("Scopes granted:")
    for scope in granted.split():
        print(f"  - {scope}")


if __name__ == "__main__":
    main()
