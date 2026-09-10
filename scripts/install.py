"""Editable installation of every distribution in the repository.

Order matters: a distribution is installed after the ones it depends on, so pip
resolves each local name against the copy in this working tree rather than
looking for it on an index.

The Gmail server is installed here for convenience, but nothing forces it to
share this environment. ``--gmail-venv`` puts it in one of its own, which is the
honest demonstration that it needs neither the agent nor an agentic framework.

``--runtime-source`` does the same for the serving library. ``ygo74-agent-runtime``
is developed alongside this repository, and publishing a release to try a fix is
a slow way to find out it was the wrong fix. Pointing at a checkout links it into
the environment instead, so an edit there is live here.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# In dependency order: a distribution never precedes one it depends on.
DISTRIBUTIONS = (
    Path("mcp-servers/protocol"),
    Path("agents/core"),
    Path("agents/maf"),
    Path("agents/mail"),
    Path("mcp-servers/reference"),
    Path("mcp-servers/gmail"),
)

EXTRAS = {
    Path("agents/maf"): "azure",
    Path("agents/mail"): "maf,native,http",
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

GMAIL = Path("mcp-servers/gmail")

# Where the Python distribution sits inside a runtime checkout. The repository is
# multi-language, so its root is not an installable project.
RUNTIME_PACKAGE = Path("packages/python")


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


def _separate_gmail_environment(venv: Path) -> None:
    """Install the Gmail server on its own, in a virtual environment of its own."""
    print(f"\n== separate environment for {GMAIL} in {venv}")
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, cwd=ROOT)  # noqa: S603
    interpreter = venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"
    installer = Installer(interpreter)
    installer.install("--editable", str(ROOT / "mcp-servers" / "protocol"))
    installer.install("--editable", str(ROOT / GMAIL))


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


def main() -> None:
    """Entry point of ``python -m scripts.install``."""
    parser = argparse.ArgumentParser(description="Install every distribution in editable mode.")
    parser.add_argument("--no-dev", action="store_true", help="Skip the development tools.")
    parser.add_argument("--gmail-venv", type=Path, help="Also install the Gmail server in its own environment.")
    parser.add_argument(
        "--runtime-source",
        type=Path,
        help="Link a ygo74-agent-runtime checkout instead of using the published release.",
    )
    arguments = parser.parse_args()

    installer = Installer(Path(sys.executable))

    # Before the distributions, so pip finds the requirement already satisfied
    # and leaves the working copy alone rather than replacing it with a wheel.
    if arguments.runtime_source is not None:
        distribution = _runtime_distribution(arguments.runtime_source)
        print(f"\n== linked ygo74-agent-runtime from {distribution}")
        installer.install("--editable", str(distribution))

    for distribution in DISTRIBUTIONS:
        installer.editable(distribution)

    if not arguments.no_dev:
        print("\n== development tools")
        installer.install(*DEVELOPMENT_TOOLS)

    if arguments.gmail_venv is not None:
        _separate_gmail_environment(arguments.gmail_venv)

    print("\nDone.")


if __name__ == "__main__":
    main()
