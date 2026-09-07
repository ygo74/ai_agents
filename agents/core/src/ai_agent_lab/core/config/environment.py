"""Loading of the local configuration file into the process environment.

The chat client resolves its own credentials from the environment. Loading the
file here gives every consumer the same values with the same precedence: a real
environment variable always wins over the file, exactly like the settings
classes behave.

No value is read, inspected or logged by the application; the file is only made
visible to the components that resolve their own configuration.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# The name of the file, declared here rather than by any one agent: every
# distribution loading it must agree on it.
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
