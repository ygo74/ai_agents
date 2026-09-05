"""Selection of the mail MCP implementation for the configured runtime mode."""

from __future__ import annotations

from pathlib import Path

from ai_agent_lab.infrastructure.config.settings import MailAgentMode, MailAgentSettings
from ai_agent_lab.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.infrastructure.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mcp.mail.contracts import MailTools
from ai_agent_lab.mcp.mail.errors import MailToolUnavailableError


class MailToolsProvider:
    """Builds the mail MCP implementation the configuration asks for.

    The agent and the skills are identical in every mode; only the object built
    here changes. That is the property the two runtime modes exist to prove.
    """

    def __init__(self, settings: MailAgentSettings, dataset_loader: MailDatasetLoader) -> None:
        self._settings = settings
        self._dataset_loader = dataset_loader

    def build(self, *, base_path: Path | None = None) -> MailTools:
        """Return the mail tools matching the configured mode."""
        if self._settings.mode is MailAgentMode.MOCK:
            return self._build_mock(base_path or Path.cwd())
        raise MailToolUnavailableError(
            "the 'mcp' mode needs a Mail MCP server; it is the next deliverable and is not wired yet. "
            "Set MAIL_AGENT_MODE=mock to run against the local dataset."
        )

    def _build_mock(self, base_path: Path) -> MailTools:
        """Build the mail tools backed by the configured dataset."""
        dataset = self._settings.mock_dataset
        resolved = dataset if dataset.is_absolute() else base_path / dataset
        return InMemoryMailTools(self._dataset_loader.load_file(resolved))
