"""Launch the Wiki HTTP factory with a selected component environment."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from ai_agent_lab.wiki.infrastructure.configuration.environment import WikiEnvironmentFile


def main() -> None:
    """Load configuration before Uvicorn and preserve it across reloads."""
    parser = argparse.ArgumentParser(description="Wiki Agent HTTP service.")
    parser.add_argument("--env-file", type=Path, help="Environment file to load (default: .env).")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind.")
    parser.add_argument("--port", type=int, default=8003, help="Port to bind.")
    parser.add_argument("--reload", action="store_true", help="Reload when source files change.")
    parser.add_argument("--ssl-certfile", type=Path, help="TLS certificate chain file.")
    parser.add_argument("--ssl-keyfile", type=Path, help="TLS private key file.")
    arguments = parser.parse_args()

    if (arguments.ssl_certfile is None) != (arguments.ssl_keyfile is None):
        parser.error("--ssl-certfile and --ssl-keyfile must be supplied together")

    WikiEnvironmentFile().load(arguments.env_file)
    tls_options = {}
    if arguments.ssl_certfile is not None and arguments.ssl_keyfile is not None:
        # Uvicorn loads the configured pair when it creates the TLS listener.
        tls_options = {"ssl_certfile": arguments.ssl_certfile, "ssl_keyfile": arguments.ssl_keyfile}

    uvicorn.run(
        "ai_agent_lab.wiki.bootstrap.service:build_app",
        factory=True,
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        **tls_options,
    )


if __name__ == "__main__":
    main()
