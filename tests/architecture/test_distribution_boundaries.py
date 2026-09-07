"""Executable enforcement of the boundaries between distributions.

The repository ships six distributions across two namespaces. Nothing in the
import statements stops one from reaching into another, so these tests do: they
fail the build when a distribution imports something it must not know about.

Three rules matter most:

- no mail MCP server ever imports the agent. A server we write and a server
  written by Google must both be reachable the same way, and the day one of our
  servers depends on our domain models, that stops being true;
- the mail agent only meets Microsoft Agent Framework in its composition root,
  so the same domain and the same skills can be assembled with LangChain or
  CrewAI later;
- neither namespace grows an ``__init__.py`` at its top level, which would turn
  a namespace package into a regular one and break the split.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Every distribution, with the directory its source tree starts at.
DISTRIBUTIONS: dict[str, Path] = {
    "ai_agent_lab.core": REPOSITORY_ROOT / "agents" / "core" / "src",
    "ai_agent_lab.maf": REPOSITORY_ROOT / "agents" / "maf" / "src",
    "ai_agent_lab.mail": REPOSITORY_ROOT / "agents" / "mail" / "src",
    "mail_mcp.protocol": REPOSITORY_ROOT / "mcp-servers" / "protocol" / "src",
    "mail_mcp.gmail": REPOSITORY_ROOT / "mcp-servers" / "gmail" / "src",
    "mail_mcp.reference": REPOSITORY_ROOT / "mcp-servers" / "reference" / "src",
}

# Which distribution may import which, itself excluded.
#
# The mail agent depends on the protocol only for its native dialect. The Google
# dialect needs none of it, which is the proof that the protocol is one dialect
# among others rather than "the contract of the agent".
ALLOWED_DISTRIBUTION_IMPORTS: dict[str, frozenset[str]] = {
    "ai_agent_lab.core": frozenset(),
    "ai_agent_lab.maf": frozenset({"ai_agent_lab.core"}),
    "ai_agent_lab.mail": frozenset({"ai_agent_lab.core", "ai_agent_lab.maf", "mail_mcp.protocol"}),
    "mail_mcp.protocol": frozenset(),
    "mail_mcp.gmail": frozenset({"mail_mcp.protocol"}),
    "mail_mcp.reference": frozenset({"mail_mcp.protocol"}),
}

# Sub-layers of the mail agent, and what each may import from the others.
#
# `config` reads settings and delivered files; it depends on nothing but the
# domain. `application` is the composition root, and the only place allowed to
# name an agentic framework.
MAIL_LAYERS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "config": frozenset({"domain"}),
    "mcp": frozenset({"domain"}),
    "skills": frozenset({"domain", "mcp"}),
    "capabilities": frozenset({"domain", "mcp", "skills"}),
    "inmemory": frozenset({"domain"}),
    "application": frozenset({"domain", "config", "mcp", "skills", "capabilities", "inmemory"}),
}

# Modules sitting directly in the mail package rather than in a sub-layer. They
# are the ports and the policies the layers agree on, so they import nothing but
# the domain.
MAIL_ROOT_MODULES = frozenset({"catalog", "mail_errors", "security_floor", "tools_port"})

AGENT_FRAMEWORK_ROOTS = frozenset({"agent_framework", "langchain", "langgraph", "crewai"})

# Transports and vendor SDKs. A layer above the adapters must not name one.
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

# Mail layers that must stay free of any agentic framework.
MAIL_LAYERS_WITHOUT_FRAMEWORKS = frozenset({"domain", "mcp", "skills", "capabilities", "inmemory", "config"})

# Mail layers that must not name a transport or a vendor SDK. `mcp` is excluded:
# the dialects are the adapters, and speaking MCP is their job.
MAIL_LAYERS_WITHOUT_SDKS = frozenset({"domain", "skills", "capabilities", "inmemory"})


class ModuleUnderTest:
    """One source module together with the imports it declares."""

    def __init__(self, distribution: str, source_root: Path, path: Path) -> None:
        self.distribution = distribution
        self._source_root = source_root
        self._path = path
        self._tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    @property
    def dotted_name(self) -> str:
        """Importable name of the module."""
        relative = self._path.relative_to(self._source_root).with_suffix("")
        return ".".join(part for part in relative.parts if part != "__init__")

    @property
    def mail_layer(self) -> str | None:
        """Sub-layer of the mail agent this module belongs to, if any."""
        if self.distribution != "ai_agent_lab.mail":
            return None
        remainder = self.dotted_name.removeprefix("ai_agent_lab.mail").lstrip(".")
        if not remainder:
            return None
        head = remainder.split(".")[0]
        return None if head in MAIL_ROOT_MODULES else head

    def imported_roots(self) -> Iterator[str]:
        """Top-level package name of every import in the module."""
        for name in self._imported_names():
            yield name.split(".", 1)[0]

    def imported_distributions(self) -> Iterator[str]:
        """Distribution of every intra-repository import in the module."""
        for name in self._imported_names():
            parts = name.split(".")
            if len(parts) >= 2 and parts[0] in {"ai_agent_lab", "mail_mcp"}:
                yield f"{parts[0]}.{parts[1]}"

    def imported_mail_layers(self) -> Iterator[str]:
        """Mail sub-layer of every import into the mail agent."""
        for name in self._imported_names():
            parts = name.split(".")
            if len(parts) >= 3 and parts[0] == "ai_agent_lab" and parts[1] == "mail":
                yield parts[2]

    def _imported_names(self) -> Iterator[str]:
        """Every module name this file imports, relative imports excluded."""
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                yield node.module


def _modules() -> list[ModuleUnderTest]:
    """Every source module of the repository, ordered for stable test ids."""
    found: list[ModuleUnderTest] = []
    for distribution, source_root in DISTRIBUTIONS.items():
        package = source_root.joinpath(*distribution.split("."))
        found.extend(ModuleUnderTest(distribution, source_root, path) for path in sorted(package.rglob("*.py")))
    return found


ALL_MODULES = _modules()
MODULE_IDS = [module.dotted_name for module in ALL_MODULES]


def test_every_distribution_has_sources():
    """The table of distributions stays in sync with what is on disk."""
    empty = [distribution for distribution in DISTRIBUTIONS if not _of(distribution)]

    assert not empty, f"no source found for {empty}"


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_distributions_only_import_what_they_declare(module: ModuleUnderTest):
    """A distribution only imports the distributions it is allowed to depend on."""
    allowed = ALLOWED_DISTRIBUTION_IMPORTS[module.distribution] | {module.distribution}
    violations = {imported for imported in module.imported_distributions() if imported not in allowed}

    assert not violations, f"{module.dotted_name} must not import {sorted(violations)}"


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_no_mail_server_knows_the_agent(module: ModuleUnderTest):
    """A mail MCP server never imports the agent.

    A server we write and a server written by somebody else must be reachable
    the same way. The moment one of ours depends on our domain models, the
    dialect stops being the only thing that adapts, and a third-party server
    becomes a second-class citizen.
    """
    if not module.distribution.startswith("mail_mcp."):
        pytest.skip("agent distribution")

    violations = {imported for imported in module.imported_distributions() if imported.startswith("ai_agent_lab.")}

    assert not violations, f"{module.dotted_name} is a server and must not import {sorted(violations)}"


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_mail_layers_point_inwards(module: ModuleUnderTest):
    """A sub-layer of the mail agent only imports the sub-layers it may."""
    layer = module.mail_layer
    if layer is None:
        pytest.skip("not a mail sub-layer")

    allowed = MAIL_LAYERS[layer] | {layer} | MAIL_ROOT_MODULES
    violations = {imported for imported in module.imported_mail_layers() if imported not in allowed}

    assert not violations, f"{module.dotted_name} must not import mail layer(s) {sorted(violations)}"


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_mail_modules_sit_in_a_declared_layer(module: ModuleUnderTest):
    """Every mail source file is either a declared layer or a declared port."""
    if module.distribution != "ai_agent_lab.mail":
        pytest.skip("not the mail agent")
    layer = module.mail_layer
    if layer is None:
        pytest.skip("port or package initialiser")

    assert layer in MAIL_LAYERS, f"{module.dotted_name} sits outside the declared mail layers"


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_business_code_ignores_agent_frameworks(module: ModuleUnderTest):
    """Domain, skills and capabilities stay free of any agentic framework.

    This is what makes a fair comparison between Microsoft Agent Framework,
    LangChain and CrewAI possible: the business logic is shared, never ported.
    Only ``ai_agent_lab.maf`` and the composition root may name one.
    """
    if module.distribution == "ai_agent_lab.maf":
        pytest.skip("the framework adapter")
    if module.mail_layer is not None and module.mail_layer not in MAIL_LAYERS_WITHOUT_FRAMEWORKS:
        pytest.skip("composition root")

    violations = AGENT_FRAMEWORK_ROOTS.intersection(module.imported_roots())

    assert not violations, f"{module.dotted_name} must not import agent framework(s) {sorted(violations)}"


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_the_agent_never_sees_a_mail_system(module: ModuleUnderTest):
    """No mail domain, skill or capability names a transport or a mail SDK.

    In particular the Mail Agent must never see Gmail, OAuth, IMAP or SMTP: it
    reaches a mailbox through an MCP tool and nothing else.
    """
    if module.mail_layer not in MAIL_LAYERS_WITHOUT_SDKS:
        pytest.skip("adapter, composition root or server")

    violations = ENTERPRISE_SDK_ROOTS.intersection(module.imported_roots())

    assert not violations, f"{module.dotted_name} must not import external system SDK(s) {sorted(violations)}"


@pytest.mark.parametrize("namespace", ["ai_agent_lab", "mail_mcp"])
def test_namespaces_stay_implicit(namespace: str):
    """No distribution declares the top level of a shared namespace.

    An ``__init__.py`` there would make the namespace a regular package, and
    whichever distribution happened to be found first would hide the others.
    """
    offenders = [
        str((source_root / namespace / "__init__.py").relative_to(REPOSITORY_ROOT))
        for source_root in {DISTRIBUTIONS[name] for name in DISTRIBUTIONS if name.startswith(f"{namespace}.")}
        if (source_root / namespace / "__init__.py").is_file()
    ]

    assert not offenders, f"{offenders} would break the {namespace} namespace"


def _of(distribution: str) -> list[ModuleUnderTest]:
    """Every module belonging to one distribution."""
    return [module for module in ALL_MODULES if module.distribution == distribution]
