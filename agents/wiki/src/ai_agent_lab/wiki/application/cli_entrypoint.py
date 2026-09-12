"""Command-line entry point of the Wiki Agent proof of concept."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from ai_agent_lab.core.config.azure_credentials import AzureIdentityCredentialProvider
from ai_agent_lab.core.config.environment import EnvironmentFile
from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.langgraph.approval import LangGraphApprovalTranslator
from ai_agent_lab.langgraph.chat_model import AzureOpenAIRoute, LangGraphChatModelFactory
from ai_agent_lab.wiki.application.composition import WikiAgentCompositionRoot, WikiAgentRuntime
from ai_agent_lab.wiki.application.console import Console, ConsoleApprovalResolver
from ai_agent_lab.wiki.application.session import WikiAgentSession
from ai_agent_lab.wiki.config.settings import (
    ChatModelSettings,
    ChatProvider,
    WikiAgentSettings,
)

_BANNER = """\
Wiki Agent ready.

Type a request, or 'exit' to leave.
Examples:
  What is in scope for the Apollo project?
  Summarise the architecture page.
  Which pages in APOLLO have gone stale?
"""

_logger = logging.getLogger(__name__)


class WikiAgentCli:
    """Reads user turns from the console and prints the agent answers."""

    def __init__(self, session: WikiAgentSession, console: Console, runtime: WikiAgentRuntime) -> None:
        self._session = session
        self._console = console
        self._runtime = runtime

    async def run(self) -> None:
        """Run the conversation until the user leaves, then release the backend."""
        try:
            await self._converse()
        finally:
            await self._runtime.aclose()

    async def _converse(self) -> None:
        """Read and answer turns until the user leaves."""
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
        still one turn of a conversation the user is in the middle of. Losing the
        session over it helps nobody. The detail goes to the log; the user gets a
        sentence.
        """
        try:
            answer = await self._session.ask(message)
        except DomainError as error:
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
    chat_model: BaseChatModel | None = None,
) -> WikiAgentCli:
    """Assemble the command-line application from the environment."""
    EnvironmentFile().load()
    settings = WikiAgentSettings()
    logging.basicConfig(level=settings.log_level.upper())

    runtime = WikiAgentCompositionRoot(
        settings,
        chat_model or build_chat_model(),
        principal=Principal(subject=settings.user_id),
        base_path=base_path or Path.cwd(),
    ).build(session_id=f"cli-{uuid.uuid4().hex[:8]}")

    console = Console()
    return WikiAgentCli(
        WikiAgentSession(
            runtime,
            ConsoleApprovalResolver(
                console,
                runtime.presenter,
                runtime.confirmation_ledger,
                runtime.user,
            ),
            LangGraphApprovalTranslator(),
        ),
        console,
        runtime,
    )


def build_chat_model() -> BaseChatModel:
    """Build the configured chat model, OpenAI or Azure OpenAI."""
    EnvironmentFile().load()
    settings = ChatModelSettings()
    factory = LangGraphChatModelFactory()
    if settings.provider is ChatProvider.AZURE_OPENAI:
        return factory.azure_openai(
            AzureOpenAIRoute(
                model=settings.azure_model,
                endpoint=settings.azure_endpoint,
                api_version=settings.azure_api_version,
            ),
            credential=AzureIdentityCredentialProvider().create_or_none(settings.azure_credential),
        )
    return factory.openai(model=settings.openai_model)


def main() -> None:
    """Entry point of the ``wiki-agent`` console script."""
    _prefer_utf8()
    asyncio.run(build_cli().run())


def _prefer_utf8() -> None:
    """Ask the terminal for UTF-8, so real page titles render as written.

    Documentation comes with accents, emoji and every script there is. A modern
    terminal handles them once the streams are UTF-8; a legacy Windows code page
    cannot, and :class:`Console` degrades those characters rather than losing the
    line. This only removes the need to.

    Failing is fine: a stream that cannot be reconfigured is one that was already
    redirected or wrapped, and the fallback still applies.
    """
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
