"""Command-line entry point of the Mail Agent proof of concept."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from agent_framework.openai import OpenAIChatClient

from ai_agent_lab.application.mail.composition import MailAgentCompositionRoot
from ai_agent_lab.application.mail.console import Console, ConsoleConfirmationPrompt
from ai_agent_lab.application.mail.session import MailAgentSession
from ai_agent_lab.domain.errors import DomainError
from ai_agent_lab.frameworks.microsoft_agent_framework.approval import MafApprovalTranslator
from ai_agent_lab.infrastructure.config.settings import MailAgentSettings

_BANNER = """\
Mail Agent ready.

Type a request, or 'exit' to leave.
Examples:
  Find unread emails from the last week.
  Summarise the conversation about Project Alpha.
  Draft a reply to John saying I will review the document tomorrow.
"""


class MailAgentCli:
    """Reads user turns from the console and prints the agent answers."""

    def __init__(self, session: MailAgentSession, console: Console) -> None:
        self._session = session
        self._console = console

    async def run(self) -> None:
        """Run the conversation until the user leaves."""
        self._console.write(_BANNER)
        while True:
            try:
                message = self._console.prompt("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                self._console.write()
                return
            if not message:
                continue
            if self._console.is_exit(message):
                return
            await self._answer(message)

    async def _answer(self, message: str) -> None:
        """Run one turn, reporting a domain failure instead of crashing."""
        try:
            answer = await self._session.ask(message)
        except DomainError as error:
            self._console.write(f"\nAgent > the request could not be completed: {error}\n")
            return
        self._console.write(f"\nAgent > {answer}\n")


def build_cli(*, base_path: Path | None = None) -> MailAgentCli:
    """Assemble the command-line application from the environment."""
    settings = MailAgentSettings()
    logging.basicConfig(level=settings.log_level.upper())

    runtime = MailAgentCompositionRoot(
        settings,
        OpenAIChatClient(),
        base_path=base_path or Path.cwd(),
    ).build(session_id=f"cli-{uuid.uuid4().hex[:8]}")

    console = Console()
    session = MailAgentSession(runtime, console, ConsoleConfirmationPrompt(console), MafApprovalTranslator())
    return MailAgentCli(session, console)


def main() -> None:
    """Entry point of the ``mail-agent`` console script."""
    asyncio.run(build_cli().run())


if __name__ == "__main__":
    main()
