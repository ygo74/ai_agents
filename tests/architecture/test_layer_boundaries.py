"""Executable enforcement of the layered architecture.

These tests fail the build when a layer reaches for something it must not know
about. They are the mechanical counterpart of ``docs/architecture.md``: the
diagram there is only credible because this file makes it true.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

import ai_agent_lab

ROOT_PACKAGE = "ai_agent_lab"
SOURCE_ROOT = Path(ai_agent_lab.__file__).parent

# Layers a given layer is allowed to import from, itself excluded.
ALLOWED_INTERNAL_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "mcp": frozenset({"domain"}),
    "skills": frozenset({"domain", "mcp"}),
    "agents": frozenset({"domain", "mcp", "skills"}),
    "frameworks": frozenset({"domain", "mcp", "skills", "agents"}),
    "infrastructure": frozenset({"domain", "mcp"}),
    "application": frozenset({"domain", "mcp", "skills", "agents", "frameworks", "infrastructure"}),
}

# Third-party roots that only the adapter layers may depend on.
AGENT_FRAMEWORK_ROOTS = frozenset({"agent_framework", "langchain", "langgraph", "crewai"})
ENTERPRISE_SDK_ROOTS = frozenset(
    {
        "google",
        "googleapiclient",
        "google_auth_oauthlib",
        "imaplib",
        "smtplib",
        "poplib",
        "email",
        "mcp",
        "openai",
        "httpx",
        "requests",
        "aiohttp",
    }
)

LAYERS_WITHOUT_FRAMEWORKS = frozenset({"domain", "mcp", "skills", "agents"})
LAYERS_WITHOUT_ENTERPRISE_SDKS = frozenset({"domain", "mcp", "skills", "agents", "application"})


class ModuleUnderTest:
    """One source module together with the imports it declares."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    @property
    def layer(self) -> str:
        """Architecture layer the module belongs to."""
        return self._path.relative_to(SOURCE_ROOT).parts[0]

    @property
    def dotted_name(self) -> str:
        """Importable name of the module."""
        relative = self._path.relative_to(SOURCE_ROOT).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        return ".".join([ROOT_PACKAGE, *parts])

    def imported_roots(self) -> Iterator[str]:
        """Top-level package name of every import in the module."""
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                yield from (alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                yield node.module.split(".", 1)[0]

    def imported_internal_layers(self) -> Iterator[str]:
        """Layer of every intra-repository import in the module."""
        for node in ast.walk(self._tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                parts = node.module.split(".")
                if len(parts) >= 2 and parts[0] == ROOT_PACKAGE:
                    yield parts[1]
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if len(parts) >= 2 and parts[0] == ROOT_PACKAGE:
                        yield parts[1]


def _modules() -> list[ModuleUnderTest]:
    """Every source module of the repository, ordered for stable test ids."""
    return [ModuleUnderTest(path) for path in sorted(SOURCE_ROOT.rglob("*.py"))]


ALL_MODULES = _modules()
MODULE_IDS = [module.dotted_name for module in ALL_MODULES]


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_module_belongs_to_a_declared_layer(module: ModuleUnderTest):
    """Every source file lives in a layer the architecture knows about."""
    if module.dotted_name == ROOT_PACKAGE:
        pytest.skip("root package initialiser")
    assert module.layer in ALLOWED_INTERNAL_IMPORTS, f"{module.dotted_name} sits outside the declared layers"


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_dependencies_point_inwards(module: ModuleUnderTest):
    """A layer only imports the layers it is allowed to depend on."""
    if module.layer not in ALLOWED_INTERNAL_IMPORTS:
        pytest.skip("root package initialiser")

    allowed = ALLOWED_INTERNAL_IMPORTS[module.layer] | {module.layer}
    violations = {layer for layer in module.imported_internal_layers() if layer not in allowed}

    assert not violations, f"{module.dotted_name} must not import layer(s) {sorted(violations)}"


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_business_layers_ignore_agent_frameworks(module: ModuleUnderTest):
    """Domain, MCP contracts, skills and agent definitions stay framework free.

    This is what makes a fair comparison between Microsoft Agent Framework,
    LangChain and CrewAI possible: the business logic is shared, never ported.
    """
    if module.layer not in LAYERS_WITHOUT_FRAMEWORKS:
        pytest.skip("adapter layer")

    violations = AGENT_FRAMEWORK_ROOTS.intersection(module.imported_roots())

    assert not violations, f"{module.dotted_name} must not import agent framework(s) {sorted(violations)}"


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_only_infrastructure_talks_to_external_systems(module: ModuleUnderTest):
    """No layer above infrastructure knows about a transport or a mail SDK.

    In particular the Mail Agent must never see Gmail, OAuth, IMAP or SMTP.
    """
    if module.layer not in LAYERS_WITHOUT_ENTERPRISE_SDKS:
        pytest.skip("infrastructure or framework adapter")

    violations = ENTERPRISE_SDK_ROOTS.intersection(module.imported_roots())

    assert not violations, f"{module.dotted_name} must not import external system SDK(s) {sorted(violations)}"


def test_the_architecture_covers_every_layer_on_disk():
    """The rule table stays in sync with the directories that actually exist."""
    on_disk = {path.name for path in SOURCE_ROOT.iterdir() if path.is_dir() and not path.name.startswith("__")}

    assert on_disk == set(ALLOWED_INTERNAL_IMPORTS)
