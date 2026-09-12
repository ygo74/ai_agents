"""Command-line entry point of the Mail Agent proof of concept."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path

from agent_framework import SupportsChatGetResponse
from ygo74.agent_runtime.domains.security.security_errors import SecurityError

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.core.config.environment import EnvironmentFile
from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.maf.approval import MafApprovalTranslator
from ai_agent_lab.maf.chat_client import MafChatClientFactory
from ai_agent_lab.mail.application.approval.console import ConsoleApprovalResolver
from ai_agent_lab.mail.application.chat_client import ConfiguredChatClientFactory
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot, MailAgentRuntime
from ai_agent_lab.mail.application.console import Console, ConsoleConfirmationPrompt
from ai_agent_lab.mail.application.session import MailAgentSession
from ai_agent_lab.mail.config.settings import ChatClientSettings, MailAgentSettings

_BANNER = """\
Mail Agent ready.

Type a request, or 'exit' to leave.
Examples:
  Find unread emails from the last week.
  Summarise the conversation about Project Alpha.
  Draft a reply to John saying I will review the document tomorrow.
"""

_logger = logging.getLogger(__name__)


class MailAgentCli:
    """Reads user turns from the console and prints the agent answers."""

    def __init__(self, session: MailAgentSession, console: Console, runtime: MailAgentRuntime) -> None:
        _logger.info("Initializing Mail Agent CLI")
        _logger.debug(
            "MailAgentCli.__init__ arguments: session_type=%s, console_type=%s, runtime_type=%s",
            type(session).__name__,
            type(console).__name__,
            type(runtime).__name__,
        )
        self._session = session
        self._console = console
        self._runtime = runtime

    async def run(self) -> None:
        """Run the conversation until the user leaves, then release the backend."""
        _logger.info("Starting Mail Agent CLI")
        _logger.debug("MailAgentCli.run arguments: none")
        try:
            await self._converse()
        finally:
            await self._runtime.aclose()

    async def _converse(self) -> None:
        """Read and answer turns until the user leaves."""
        _logger.info("Starting Mail Agent CLI conversation loop")
        _logger.debug("MailAgentCli._converse arguments: none")
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
        """Run one turn, reporting a failure instead of ending the session.

        A domain failure is expected and named. Anything else - the model
        provider refusing a request, a transport giving up - is not, but it is
        still one turn of a conversation the user is in the middle of. Losing
        the session over it, along with every draft prepared in it, helps
        nobody. The detail goes to the log; the user gets a sentence.
        """
        # Called once per console-loop iteration, so its entry stays at DEBUG;
        # the loop itself emits the corresponding INFO event.
        _logger.debug("MailAgentCli._answer arguments: message_length=%d", len(message))
        try:
            answer = await self._session.ask(message)
        except (DomainError, SecurityError) as error:
            self._console.write(f"\nAgent > the request could not be completed: {error}\n")
            return
        except Exception as error:
            _logger.exception("turn failed")
            self._console.write(f"\nAgent > that turn failed ({type(error).__name__}). Nothing was changed.\n")
            return
        self._console.write(f"\nAgent > {answer}\n")


def build_cli(
    *,
    base_path: Path | None = None,
    chat_client: SupportsChatGetResponse | None = None,
) -> MailAgentCli:
    """Assemble the command-line application from the environment.

    The chat client is chosen by ``AGENT_CHAT_PROVIDER``. A client can also be
    injected by another host or by a test.
    """
    _logger.info("Building Mail Agent CLI")
    _logger.debug(
        "build_cli arguments: base_path=%s, injected_chat_client=%s",
        base_path,
        chat_client is not None,
    )
    EnvironmentFile().load()
    settings = MailAgentSettings()
    logging.basicConfig(level=settings.log_level.upper())

    runtime = MailAgentCompositionRoot(
        settings,
        chat_client or build_chat_client(),
        base_path=base_path or Path.cwd(),
    ).build(session_id=f"cli-{uuid.uuid4().hex[:8]}")

    console = Console()
    resolver = ConsoleApprovalResolver(
        runtime.presenter,
        ConsoleConfirmationPrompt(console),
        console,
        runtime.confirmation_ledger,
        runtime.policy,
        runtime.user,
    )
    session = MailAgentSession(runtime, resolver, MafApprovalTranslator())
    return MailAgentCli(session, console, runtime)


def build_chat_client() -> SupportsChatGetResponse:
    """Build the configured chat client, OpenAI or Azure OpenAI."""
    _logger.info("Building Mail Agent chat client")
    _logger.debug("build_chat_client arguments: none")
    EnvironmentFile().load()
    return ConfiguredChatClientFactory(
        ChatClientSettings(),
        MafChatClientFactory(),
        AzureIdentityCredentialProvider(),
    ).build()


def main() -> None:
    """Entry point of the ``mail-agent`` console script."""
    _logger.info("Starting Mail Agent command-line entry point")
    _logger.debug("main arguments: none")
    _prefer_utf8()
    asyncio.run(build_cli().run())


def _prefer_utf8() -> None:
    """Ask the terminal for UTF-8, so real mail subjects render as written.

    Mail comes with accents, emoji and every script there is. A modern terminal
    handles them once the streams are UTF-8; a legacy Windows code page cannot,
    and :class:`Console` degrades those characters rather than losing the line.
    This only removes the need to.

    Failing is fine: a stream that cannot be reconfigured is one that was
    already redirected or wrapped, and the fallback still applies.
    """
    _logger.info("Configuring Mail Agent terminal encoding")
    _logger.debug("_prefer_utf8 arguments: streams=%s", ("stdout", "stderr"))
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    main()
