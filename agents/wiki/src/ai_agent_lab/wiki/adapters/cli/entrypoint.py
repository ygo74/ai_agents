"""Command-line entry point of the Wiki Agent proof of concept."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.errors import DomainError
from ygo74.agent_runtime.domains.security.security_errors import SecurityError

from ai_agent_lab.core.observability.logging_config import setup_logging
from ai_agent_lab.wiki.adapters.cli.console import Console, ConsoleApprovalResolver
from ai_agent_lab.wiki.adapters.langchain.session import WikiAgentSession
from ai_agent_lab.wiki.bootstrap.chat_model import build_chat_model
from ai_agent_lab.wiki.bootstrap.composition import WikiAgentCompositionRoot, WikiAgentRuntime
from ai_agent_lab.wiki.infrastructure.configuration.environment import WikiEnvironmentFile
from ai_agent_lab.wiki.infrastructure.configuration.settings import WikiAgentSettings

_BANNER = """\
Wiki Agent ready.

Type a request, or 'exit' to leave.
Examples:
  What is in scope for the Apollo project?
  Summarise the architecture page.
  Which pages in APOLLO have gone stale?
"""

_logger = logging.getLogger("ai_agent_lab.wiki.cli")


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
        _logger.info("Wiki Agent CLI conversation loop started")
        self._console.write(_BANNER)
        while True:
            try:
                message = self._console.prompt("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                _logger.info("Wiki Agent CLI received exit signal")
                self._console.write()
                return
            if not message:
                continue
            if self._console.is_exit(message):
                _logger.info("Wiki Agent CLI user requested exit")
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
        _logger.info("processing user turn (length=%d)", len(message))
        _logger.debug("user turn input: %r", message)
        try:
            answer = await self._session.ask(message)
        except (DomainError, SecurityError) as error:
            _logger.warning("user turn failed with domain error: %s: %s", type(error).__name__, error)
            self._console.write(f"\nAgent > the request could not be completed: {error}\n")
            return
        except Exception as error:
            _logger.exception("user turn failed with unexpected error")
            self._console.write(f"\nAgent > that turn failed ({type(error).__name__}). Nothing was changed.\n")
            return
        _logger.info("user turn finished successfully (answer length=%d)", len(answer))
        _logger.debug("agent answer: %r", answer)
        self._console.write(f"\nAgent > {answer}\n")


def _configure_logging(level_name: str | None = None, env_file: Path | None = None) -> None:
    """Configure logging from CLI or agent and shared environment settings."""
    WikiEnvironmentFile().load(env_file)
    setup_logging(
        default_level=WikiAgentSettings().log_level,
        level_name=level_name,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse optional command-line arguments."""
    parser = argparse.ArgumentParser(description="Wiki Agent CLI")
    parser.add_argument("--env-file", type=Path, help="Environment file to load (default: .env).")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type=str.upper,
        default=None,
        help="Logging level (overrides WIKI_AGENT_LOG_LEVEL and LOG_LEVEL)",
    )
    return parser.parse_args(argv)


def build_cli(
    *,
    base_path: Path | None = None,
    chat_model: BaseChatModel | None = None,
    log_level: str | None = None,
    env_file: Path | None = None,
) -> WikiAgentCli:
    """Assemble the command-line application from the environment."""
    _configure_logging(log_level, env_file)
    settings = WikiAgentSettings()
    _logger.info("Initializing Wiki Agent CLI (mode=%s, user_id=%s)", settings.mode.value, settings.user_id)
    _logger.debug("Wiki Agent settings: log_level=%s, mock_dataset=%s", settings.log_level, settings.mock_dataset)

    _logger.info("Building chat model and WikiAgentCompositionRoot...")
    model = chat_model or build_chat_model()
    runtime = WikiAgentCompositionRoot(
        settings,
        model,
        principal=AgentPrincipal(subject=settings.user_id),
        base_path=base_path or Path.cwd(),
    ).build(session_id=f"cli-{uuid.uuid4().hex[:8]}")

    console = Console()
    _logger.info("Wiki Agent CLI session ready")
    return WikiAgentCli(
        WikiAgentSession(
            runtime,
            ConsoleApprovalResolver(
                console,
                runtime.presenter,
                runtime.confirmation_ledger,
                runtime.user,
            ),
        ),
        console,
        runtime,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point of the ``wiki-agent`` console script."""
    _prefer_utf8()
    args = _parse_args(argv)
    asyncio.run(build_cli(log_level=args.log_level, env_file=args.env_file).run())


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
