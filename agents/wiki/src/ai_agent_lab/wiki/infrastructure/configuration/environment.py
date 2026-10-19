"""Select the Wiki host environment file before constructing dependencies."""

from __future__ import annotations

import os
from pathlib import Path

from ygo74.agent_runtime.domains.configuration.environment import ENV_FILE, EnvironmentFile

ENV_FILE_VARIABLE = "WIKI_AGENT_ENV_FILE"


class WikiEnvironmentFile:
    """Keep one selected file across factories and HTTP reload subprocesses."""

    def load(self, path: Path | None = None) -> None:
        """Load the selected file without overriding process environment values."""
        selected = path or Path(os.environ.get(ENV_FILE_VARIABLE, ENV_FILE))
        explicit = path is not None or ENV_FILE_VARIABLE in os.environ
        if explicit and not selected.is_file():
            raise FileNotFoundError(f"Wiki environment file does not exist: {selected}")
        if explicit:
            os.environ[ENV_FILE_VARIABLE] = str(selected.resolve())
        EnvironmentFile(selected).load()
