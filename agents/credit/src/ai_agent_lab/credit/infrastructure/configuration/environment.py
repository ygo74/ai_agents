"""Preserve the Credit HTTP launcher's environment selection across reload workers."""

import os
from pathlib import Path

from ygo74.agent_runtime.domains.configuration.environment import EnvironmentFile

ENV_FILE_VARIABLE = "CREDIT_AGENT_ENV_FILE"


class CreditEnvironmentFile:
    """Load one operator-selected file without overriding the process environment."""

    def load(self, path: Path | None = None) -> None:
        """Validate explicit paths and preserve their absolute form for Uvicorn reload.

        Args:
            path: Explicit environment file; absent selects the preserved path or .env.
        """
        selected = path or (Path(os.environ[ENV_FILE_VARIABLE]) if os.environ.get(ENV_FILE_VARIABLE) else None)
        if selected is not None:
            if not selected.is_file():
                raise FileNotFoundError(selected)
            selected = selected.resolve()
            os.environ[ENV_FILE_VARIABLE] = str(selected)
        EnvironmentFile(selected).load()
