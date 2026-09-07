"""Reading of the local configuration file.

The server resolves its own credentials from the environment. Loading the file
here gives it the same values with the same precedence as any other consumer: a
real environment variable always wins over the file.

No value is inspected or logged; the file is only made visible to the settings
that read it.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = ".env"


class EnvironmentFile:
    """Makes the values of the local configuration file visible to the process."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(ENV_FILE)

    def load(self) -> bool:
        """Load the file when it exists, never overriding what is already set."""
        if not self._path.is_file():
            return False
        return load_dotenv(self._path, override=False)
