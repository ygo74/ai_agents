"""Editable installation of the distributions in this repository.

An **environment** is a deployment unit: the set of distributions one thing needs
and nothing more. Each agent gets its own, which is not tidiness for its own
sake. The Mail Agent runs on Microsoft Agent Framework and the Wiki Agent on
LangChain; installing both in one place has already been observed to move a
shared transitive dependency under the other's feet, and a framework comparison
run in a contaminated environment measures the contamination.

    python -m scripts.install                                  # dev, in place
    python -m scripts.install --env wiki-agent --into .venvs/wiki-agent
    python -m scripts.install --list                           # what is on offer

Within an environment, order matters: a distribution is installed after the ones
it depends on, so pip resolves each local name against the copy in this working
tree rather than looking for it on an index.

``--runtime-source`` links a ``ygo74-agent-runtime`` checkout instead of using the
published release. That library is developed alongside this repository, and
publishing a release to try a fix is a slow way to find out it was the wrong fix.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CORE = Path("agents/core")
MAF = Path("agents/maf")
LANGGRAPH = Path("agents/langgraph")
MAIL = Path("agents/mail")
WIKI = Path("agents/wiki")
MAIL_PROTOCOL = Path("mcp-servers/protocol")
MAIL_REFERENCE = Path("mcp-servers/reference")
GMAIL = Path("mcp-servers/gmail")
WIKI_PROTOCOL = Path("mcp-servers/wiki-protocol")
WIKI_REFERENCE = Path("mcp-servers/wiki-reference")

EXTRAS = {
    CORE: "http",
    MAF: "azure",
    LANGGRAPH: "azure",
    MAIL: "maf,native,http",
    WIKI: "langgraph,native,http",
}

DEVELOPMENT_TOOLS = (
    "pytest>=8,<9",
    "pytest-asyncio>=0.24,<2",
    "ruff>=0.9",
    "mypy>=1.14",
    "types-pyyaml>=6,<7",
    # The HTTP surface is exercised through Starlette's TestClient, which needs
    # httpx to drive the real routes rather than a mocked application.
    "httpx>=0.27",
)

# Where the Python distribution sits inside a runtime checkout. The repository is
# multi-language, so its root is not an installable project.
RUNTIME_PACKAGE = Path("packages/python")


@dataclass(frozen=True, slots=True)
class Environment:
    """One deployment unit and what belongs in it."""

    name: str
    description: str
    distributions: tuple[Path, ...]
    development_tools: bool = False
    notes: tuple[str, ...] = field(default=())


ENVIRONMENTS: dict[str, Environment] = {
    "dev": Environment(
        name="dev",
        description="Everything, plus the development tools.",
        # The architecture and boundary tests scan every distribution, so the
        # environment the suite runs in has to hold all of them. This is the one
        # place where the two agentic frameworks legitimately coexist.
        distributions=(
            MAIL_PROTOCOL,
            WIKI_PROTOCOL,
            CORE,
            MAF,
            LANGGRAPH,
            MAIL,
            WIKI,
            MAIL_REFERENCE,
            WIKI_REFERENCE,
            GMAIL,
        ),
        development_tools=True,
    ),
    "mail-agent": Environment(
        name="mail-agent",
        description="The Mail Agent, on Microsoft Agent Framework.",
        distributions=(MAIL_PROTOCOL, CORE, MAF, MAIL, MAIL_REFERENCE),
        notes=("No LangChain package enters this environment.",),
    ),
    "wiki-agent": Environment(
        name="wiki-agent",
        description="The Wiki Agent, on LangChain / LangGraph.",
        distributions=(WIKI_PROTOCOL, CORE, LANGGRAPH, WIKI, WIKI_REFERENCE),
        notes=("No agent-framework package enters this environment.",),
    ),
    "mail-mcp-gmail": Environment(
        name="mail-mcp-gmail",
        description="The Gmail MCP server, alone.",
        distributions=(MAIL_PROTOCOL, GMAIL),
        notes=(
            "Proof that a server needs neither an agent nor an agentic framework.",
            "Point the `command` of config/mcp/gmail-api.yaml at this interpreter.",
        ),
    ),
    "wiki-mcp-reference": Environment(
        name="wiki-mcp-reference",
        description="The reference wiki MCP server, alone.",
        distributions=(WIKI_PROTOCOL, WIKI_REFERENCE),
        notes=("The Confluence-backed server is mcp-atlassian, which we do not vendor.",),
    ),
}

DEFAULT_ENVIRONMENT = "dev"


class Installer:
    """Runs pip against one interpreter."""

    def __init__(self, python: Path) -> None:
        self._python = python

    def install(self, *arguments: str) -> None:
        """Install the given requirements, failing loudly."""
        subprocess.run(  # noqa: S603 - arguments are built here, never taken from input
            [str(self._python), "-m", "pip", "install", *arguments],
            check=True,
            cwd=ROOT,
        )

    def editable(self, distribution: Path) -> None:
        """Install one local distribution in editable mode."""
        extras = EXTRAS.get(distribution)
        target = str(distribution) if extras is None else f"{distribution}[{extras}]"
        print(f"\n== {target}")
        self.install("--editable", target)


def _interpreter_of(venv: Path) -> Path:
    """Return the interpreter of a virtual environment on this platform."""
    return venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"


def _prepared_interpreter(environment: Environment, into: Path | None) -> Path:
    """Return the interpreter to install into, creating the environment if needed.

    Installing into the running interpreter stays the default, so a developer who
    has already activated an environment is not made to name it twice.
    """
    if into is None:
        return Path(sys.executable)

    if not into.exists():
        print(f"\n== creating {into}")
        subprocess.run([sys.executable, "-m", "venv", str(into)], check=True, cwd=ROOT)  # noqa: S603
    interpreter = _interpreter_of(into)
    if not interpreter.exists():
        raise SystemExit(f"{into} is not a usable virtual environment: no interpreter at {interpreter}")
    print(f"\n== environment {environment.name!r} in {into}")
    return interpreter


def _missing_distributions(environment: Environment) -> list[Path]:
    """Return the distributions of an environment that are not on disk yet."""
    return [path for path in environment.distributions if not (ROOT / path / "pyproject.toml").is_file()]


def _runtime_distribution(checkout: Path) -> Path:
    """Locate the installable Python project inside a runtime checkout.

    Both layouts are accepted - the repository root or the Python package
    directly - because being wrong about which one to pass is a five-minute
    detour, and the answer is knowable from the filesystem.
    """
    resolved = checkout.expanduser().resolve()
    for candidate in (resolved / RUNTIME_PACKAGE, resolved):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    raise SystemExit(f"no installable Python project under {resolved}: expected a pyproject.toml")


def _print_environments() -> None:
    """Describe what may be installed."""
    print("Environments:\n")
    for environment in ENVIRONMENTS.values():
        print(f"  {environment.name:<20} {environment.description}")
        for note in environment.notes:
            print(f"  {'':<20} {note}")
    print(f"\nDefault: {DEFAULT_ENVIRONMENT}. Use --env <name> --into .venvs/<name>.")


def _selected(name: str) -> Environment:
    """Return the requested environment, or fail with the list of names."""
    environment = ENVIRONMENTS.get(name)
    if environment is None:
        known = ", ".join(ENVIRONMENTS)
        raise SystemExit(f"unknown environment {name!r}: expected one of {known}")
    return environment


def _parse_arguments() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Install a deployment environment in editable mode.")
    parser.add_argument("--env", default=DEFAULT_ENVIRONMENT, help="Which environment to install.")
    parser.add_argument(
        "--into",
        type=Path,
        help="Virtual environment to install into, created if absent. Defaults to the running interpreter.",
    )
    parser.add_argument("--list", action="store_true", help="List the environments and exit.")
    parser.add_argument("--no-dev", action="store_true", help="Skip the development tools.")
    parser.add_argument(
        "--runtime-source",
        type=Path,
        help="Link a ygo74-agent-runtime checkout instead of using the published release.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point of ``python -m scripts.install``."""
    arguments = _parse_arguments()

    if arguments.list:
        _print_environments()
        return

    environment = _selected(arguments.env)
    missing = _missing_distributions(environment)
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise SystemExit(f"environment {environment.name!r} needs distributions that do not exist yet: {names}")

    installer = Installer(_prepared_interpreter(environment, arguments.into))

    # Before the distributions, so pip finds the requirement already satisfied
    # and leaves the working copy alone rather than replacing it with a wheel.
    if arguments.runtime_source is not None:
        distribution = _runtime_distribution(arguments.runtime_source)
        print(f"\n== linked ygo74-agent-runtime from {distribution}")
        installer.install("--editable", str(distribution))

    for distribution in environment.distributions:
        installer.editable(distribution)

    if environment.development_tools and not arguments.no_dev:
        print("\n== development tools")
        installer.install(*DEVELOPMENT_TOOLS)

    print("\nDone.")


if __name__ == "__main__":
    main()
