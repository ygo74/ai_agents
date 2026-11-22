"""Launch the shared runtime HTTP host for the Credit agent."""

import argparse
import os
from pathlib import Path

import uvicorn

from ai_agent_lab.credit.infrastructure.configuration.environment import CreditEnvironmentFile


def main() -> None:
    """Parse listener/configuration options and load them before reload workers start."""
    parser = argparse.ArgumentParser(description="Corporate Credit Analyst HTTP service")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--ssl-certfile", type=Path)
    parser.add_argument("--ssl-keyfile", type=Path)
    args = parser.parse_args()
    if (args.ssl_certfile is None) != (args.ssl_keyfile is None):
        parser.error("--ssl-certfile and --ssl-keyfile must be supplied together")
    CreditEnvironmentFile().load(args.env_file)
    if args.config:
        os.environ["YGO74_AGENT_RUNTIME_CONFIG_DIR"] = str(args.config.resolve())
    options = {}
    if args.ssl_certfile is not None:
        options = {"ssl_certfile": args.ssl_certfile, "ssl_keyfile": args.ssl_keyfile}
    uvicorn.run("ai_agent_lab.credit.bootstrap.service:build_app", factory=True,
                host=args.host, port=args.port, reload=args.reload, **options)


if __name__ == "__main__":
    main()
