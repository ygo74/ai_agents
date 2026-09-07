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

from mail_mcp.gmail.api import GmailApiClient
from mail_mcp.gmail.credentials import GmailCredentials, GmailCredentialSettings
from mail_mcp.gmail.environment import EnvironmentFile
from mail_mcp.gmail.loopback import LoopbackConsent
from mail_mcp.gmail.mailbox import GmailMailbox


class GmailConsent:
    """Obtains a grant and proves it works."""

    def __init__(self, credentials: GmailCredentials) -> None:
        self._credentials = credentials

    async def run(self) -> tuple[int, str]:
        """Authorise, then read the labels back."""
        await self._credentials.authorise()
        mailbox = GmailMailbox(GmailApiClient(self._credentials))
        try:
            labels = await mailbox.list_labels()
        finally:
            await mailbox.aclose()
        return len(labels.labels), self._credentials.granted_scopes()


def main() -> None:
    """Entry point of the ``mail-mcp-gmail-authorise`` command."""
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
