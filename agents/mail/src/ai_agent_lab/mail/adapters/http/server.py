"""Launch the Mail HTTP factory with a selected component environment."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from ai_agent_lab.mail.infrastructure.configuration.environment import MailEnvironmentFile


def main() -> None:
    """Load configuration before Uvicorn and preserve it across reloads."""
    parser = argparse.ArgumentParser(description="Mail Agent HTTP service.")
    parser.add_argument("--env-file", type=Path, help="Environment file to load (default: .env).")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind.")
    parser.add_argument("--port", type=int, default=8002, help="Port to bind.")
    parser.add_argument("--reload", action="store_true", help="Reload when source files change.")
    arguments = parser.parse_args()
    MailEnvironmentFile().load(arguments.env_file)
    uvicorn.run(
        "ai_agent_lab.mail.bootstrap.service:build_app",
        factory=True,
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
    )


if __name__ == "__main__":
    main()
