"""Location of the configuration delivered alongside the code.

Agent instructions, skill packages and MCP bindings are delivered separately
from the code, so their location is resolved at runtime rather than packaged.
``config/`` at the repository root is the default; ``AI_AGENT_LAB_CONFIG_DIR``
overrides it.

This directory is a trusted input: it is provided by whoever operates the agent,
never by content retrieved from an MCP server. Nothing read here is treated as
untrusted material, which is precisely why it must not be writable by a user of
the agent.
"""

from __future__ import annotations

import os
from pathlib import Path

from ai_agent_lab.domain.errors import DomainError

CONFIG_DIR_VARIABLE = "AI_AGENT_LAB_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "config"


class ConfigurationNotFoundError(DomainError):
    """Raised when the configuration directory or one of its files is missing."""


class ConfigurationDirectory:
    """Resolves where the delivered configuration lives."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @classmethod
    def resolve(cls, *, base_path: Path | None = None) -> ConfigurationDirectory:
        """Return the configured directory, or the default next to the code."""
        override = os.environ.get(CONFIG_DIR_VARIABLE, "").strip()
        if override:
            return cls(Path(override))
        return cls((base_path or Path.cwd()) / DEFAULT_CONFIG_DIR)

    @property
    def path(self) -> Path:
        """The resolved directory, which may not exist yet."""
        return self._path

    def require(self, *parts: str) -> Path:
        """Return an existing file or directory below the configuration root."""
        candidate = self._path.joinpath(*parts)
        if not candidate.exists():
            raise ConfigurationNotFoundError(
                f"{candidate} is missing; set {CONFIG_DIR_VARIABLE} to the delivered configuration"
            )
        return candidate

    def children(self, *parts: str) -> tuple[Path, ...]:
        """Return the sub-directories of a configuration folder, name ordered."""
        parent = self.require(*parts)
        return tuple(sorted((child for child in parent.iterdir() if child.is_dir()), key=lambda p: p.name))
