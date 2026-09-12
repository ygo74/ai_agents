"""Executable enforcement of the boundaries between distributions.

The repository ships ten distributions across three namespaces. Nothing in the
import statements stops one from reaching into another, so these tests do: they
fail the build when a distribution imports something it must not know about.

Four rules matter most:

- no MCP server ever imports an agent. A server we write and a server written by
  Google or by `sooperset` must all be reachable the same way, and the day one of
  ours depends on our domain models, that stops being true;
- an agent only meets its agentic framework in its composition root, so the same
  domain and the same skills can be assembled with another one later;
- **no agent depends on two frameworks**. The Mail Agent runs on Microsoft Agent
  Framework and the Wiki Agent on LangChain, and that separation is what makes
  the comparison between them mean anything;
- no namespace grows an ``__init__.py`` at its top level, which would turn a
  namespace package into a regular one and break the split.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

AGENTS = REPOSITORY_ROOT / "agents"
SERVERS = REPOSITORY_ROOT / "mcp-servers"

# Every distribution, with the directory its source tree starts at.
DISTRIBUTIONS: dict[str, Path] = {
    "ai_agent_lab.core": AGENTS / "core" / "src",
    "ai_agent_lab.maf": AGENTS / "maf" / "src",
    "ai_agent_lab.langgraph": AGENTS / "langgraph" / "src",
    "ai_agent_lab.mail": AGENTS / "mail" / "src",
    "ai_agent_lab.wiki": AGENTS / "wiki" / "src",
    "mail_mcp.protocol": SERVERS / "protocol" / "src",
    "mail_mcp.gmail": SERVERS / "gmail" / "src",
    "mail_mcp.reference": SERVERS / "reference" / "src",
    "wiki_mcp.protocol": SERVERS / "wiki-protocol" / "src",
    "wiki_mcp.reference": SERVERS / "wiki-reference" / "src",
}

# Which distribution may import which, itself excluded.
#
# An agent depends on the protocol only for its native dialect. A third-party
# dialect needs none of it, which is the proof that the protocol is one dialect
# among others rather than "the contract of the agent".
#
# Each agent names exactly one framework adapter.
ALLOWED_DISTRIBUTION_IMPORTS: dict[str, frozenset[str]] = {
    "ai_agent_lab.core": frozenset(),
    "ai_agent_lab.maf": frozenset({"ai_agent_lab.core"}),
    "ai_agent_lab.langgraph": frozenset({"ai_agent_lab.core"}),
    "ai_agent_lab.mail": frozenset({"ai_agent_lab.core", "ai_agent_lab.maf", "mail_mcp.protocol"}),
    "ai_agent_lab.wiki": frozenset({"ai_agent_lab.core", "ai_agent_lab.langgraph", "wiki_mcp.protocol"}),
    "mail_mcp.protocol": frozenset(),
    "mail_mcp.gmail": frozenset({"mail_mcp.protocol"}),
    "mail_mcp.reference": frozenset({"mail_mcp.protocol"}),
    "wiki_mcp.protocol": frozenset(),
    "wiki_mcp.reference": frozenset({"wiki_mcp.protocol"}),
}

# The distributions that are agents, and the framework adapter each is allowed to
# use. An agent naming the other one would make a framework comparison worthless.
AGENT_DISTRIBUTIONS: dict[str, str] = {
    "ai_agent_lab.mail": "ai_agent_lab.maf",
    "ai_agent_lab.wiki": "ai_agent_lab.langgraph",
}

# The framework adapters, and the third-party root each is allowed to import.
FRAMEWORK_ADAPTERS: dict[str, frozenset[str]] = {
    "ai_agent_lab.maf": frozenset({"agent_framework"}),
    "ai_agent_lab.langgraph": frozenset({"langchain", "langchain_core", "langchain_openai", "langgraph"}),
}

# Sub-layers of an agent, and what each may import from the others.
#
# `config` reads settings and delivered files; it depends on nothing but the
# domain. `application` is the composition root, and the only place allowed to
# name an agentic framework.
AGENT_LAYERS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "config": frozenset({"domain"}),
    "mcp": frozenset({"domain"}),
    "skills": frozenset({"domain", "mcp"}),
    "capabilities": frozenset({"domain", "mcp", "skills"}),
    "inmemory": frozenset({"domain"}),
    "application": frozenset({"domain", "config", "mcp", "skills", "capabilities", "inmemory"}),
}

# Modules sitting directly in an agent package rather than in a sub-layer. They
# are the ports and the policies the layers agree on, so they import nothing but
# the domain.
AGENT_ROOT_MODULES = frozenset({"catalog", "mail_errors", "wiki_errors", "security_floor", "tools_port"})

AGENT_FRAMEWORK_ROOTS = frozenset(
    {"agent_framework", "langchain", "langchain_core", "langchain_openai", "langgraph", "crewai"}
)

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
        "atlassian",
        "mcp",
        "openai",
        "httpx",
        "requests",
        "aiohttp",
    }
)

# Agent layers that must stay free of any agentic framework.
LAYERS_WITHOUT_FRAMEWORKS = frozenset({"domain", "mcp", "skills", "capabilities", "inmemory", "config"})

# Agent layers that must not name a transport or a vendor SDK. `mcp` is excluded:
# the dialects are the adapters, and speaking MCP is their job.
LAYERS_WITHOUT_SDKS = frozenset({"domain", "skills", "capabilities", "inmemory"})

# `ygo74-agent-runtime` is a foundation dependency now that it owns the security
# model and the agent contracts, so naming it is not in itself a layer violation.
# One of its domains is a transport all the same: `domains.endpoints` is where
# FastAPI lives. A module that must stay free of a transport must stay free of
# that domain, which is what this prefix pins. Without it, the property the layers
# used to have by construction - `core` knew no web stack - would be gone with no
# test to notice.
RUNTIME_TRANSPORT_MODULE = "ygo74.agent_runtime.domains.endpoints"

# The one part of `core` allowed to know a transport. Everything else in that
# distribution - the security model, the reasoning port, the configuration
# loaders - must import without one.
CORE_SERVING_PREFIX = "ai_agent_lab.core.serving"

NAMESPACES = ("ai_agent_lab", "mail_mcp", "wiki_mcp")


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
    def agent_layer(self) -> str | None:
        """Sub-layer of the agent this module belongs to, if any."""
        if self.distribution not in AGENT_DISTRIBUTIONS:
            return None
        remainder = self.dotted_name.removeprefix(self.distribution).lstrip(".")
        if not remainder:
            return None
        head = remainder.split(".")[0]
        return None if head in AGENT_ROOT_MODULES else head

    def imported_roots(self) -> Iterator[str]:
        """Top-level package name of every import in the module."""
        for name in self._imported_names():
            yield name.split(".", 1)[0]

    def imported_modules(self) -> Iterator[str]:
        """Full dotted name of every import in the module."""
        yield from self._imported_names()

    def imported_distributions(self) -> Iterator[str]:
        """Distribution of every intra-repository import in the module."""
        for name in self._imported_names():
            parts = name.split(".")
            if len(parts) >= 2 and parts[0] in {"ai_agent_lab", "mail_mcp", "wiki_mcp"}:
                yield f"{parts[0]}.{parts[1]}"

    def imported_agent_layers(self) -> Iterator[str]:
        """Sub-layer of every import into this module's own agent."""
        namespace, agent = self.distribution.split(".")
        for name in self._imported_names():
            parts = name.split(".")
            if len(parts) >= 3 and parts[0] == namespace and parts[1] == agent:
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


def _must_avoid_the_transport(module: ModuleUnderTest) -> bool:
    """Whether this module has to import without a web stack.

    Two families qualify: the business layers of an agent, and every part of
    `core` outside `core.serving`.
    """
    if module.distribution == "ai_agent_lab.core":
        return not module.dotted_name.startswith(CORE_SERVING_PREFIX)
    return module.agent_layer in LAYERS_WITHOUT_SDKS


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
def test_no_server_knows_an_agent(module: ModuleUnderTest):
    """An MCP server never imports an agent.

    A server we write and a server written by somebody else must be reachable
    the same way. The moment one of ours depends on our domain models, the
    dialect stops being the only thing that adapts, and a third-party server
    becomes a second-class citizen.
    """
    if module.distribution.startswith("ai_agent_lab."):
        pytest.skip("agent distribution")

    violations = {imported for imported in module.imported_distributions() if imported.startswith("ai_agent_lab.")}

    assert not violations, f"{module.dotted_name} is a server and must not import {sorted(violations)}"


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_agent_layers_point_inwards(module: ModuleUnderTest):
    """A sub-layer of an agent only imports the sub-layers it may."""
    layer = module.agent_layer
    if layer is None:
        pytest.skip("not an agent sub-layer")

    allowed = AGENT_LAYERS[layer] | {layer} | AGENT_ROOT_MODULES
    violations = {imported for imported in module.imported_agent_layers() if imported not in allowed}

    assert not violations, f"{module.dotted_name} must not import layer(s) {sorted(violations)}"


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_agent_modules_sit_in_a_declared_layer(module: ModuleUnderTest):
    """Every agent source file is either a declared layer or a declared port."""
    if module.distribution not in AGENT_DISTRIBUTIONS:
        pytest.skip("not an agent")
    layer = module.agent_layer
    if layer is None:
        pytest.skip("port or package initialiser")

    assert layer in AGENT_LAYERS, f"{module.dotted_name} sits outside the declared layers"


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_business_code_ignores_agent_frameworks(module: ModuleUnderTest):
    """Domain, skills and capabilities stay free of any agentic framework.

    This is what makes a fair comparison between Microsoft Agent Framework,
    LangChain and CrewAI possible: the business logic is shared, never ported.
    Only a framework adapter and a composition root may name one.
    """
    if module.distribution in FRAMEWORK_ADAPTERS:
        pytest.skip("a framework adapter")
    if module.agent_layer is not None and module.agent_layer not in LAYERS_WITHOUT_FRAMEWORKS:
        pytest.skip("composition root")

    violations = AGENT_FRAMEWORK_ROOTS.intersection(module.imported_roots())

    assert not violations, f"{module.dotted_name} must not import agent framework(s) {sorted(violations)}"


@pytest.mark.security
@pytest.mark.parametrize("distribution", sorted(AGENT_DISTRIBUTIONS), ids=sorted(AGENT_DISTRIBUTIONS))
def test_an_agent_depends_on_one_framework_only(distribution: str):
    """No agent names two framework adapters.

    Depending on both would let a deployment carry Microsoft Agent Framework and
    LangChain at once. The environments in ``scripts/install.py`` exist precisely
    so that never happens, and this is the check that keeps the code honest about
    it: measuring two frameworks in one process measures neither.
    """
    forbidden = set(FRAMEWORK_ADAPTERS) - {AGENT_DISTRIBUTIONS[distribution]}
    offenders = {
        module.dotted_name: sorted(forbidden.intersection(module.imported_distributions()))
        for module in _of(distribution)
        if forbidden.intersection(module.imported_distributions())
    }

    assert not offenders, f"{distribution} must use {AGENT_DISTRIBUTIONS[distribution]} alone: {offenders}"


@pytest.mark.parametrize("distribution", sorted(FRAMEWORK_ADAPTERS), ids=sorted(FRAMEWORK_ADAPTERS))
def test_a_framework_adapter_imports_its_own_framework(distribution: str):
    """An adapter reaches the third-party framework, not something like it.

    ``ai_agent_lab.langgraph`` and the real ``langgraph`` share a final name.
    Python 3 resolves imports absolutely, so this works - but getting it wrong
    would be silent, and the adapter would quietly adapt itself.
    """
    imported = {root for module in _of(distribution) for root in module.imported_roots()}

    assert FRAMEWORK_ADAPTERS[distribution].intersection(imported), (
        f"{distribution} imports none of {sorted(FRAMEWORK_ADAPTERS[distribution])}"
    )


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_an_agent_never_sees_an_enterprise_system(module: ModuleUnderTest):
    """No domain, skill or capability names a transport or a vendor SDK.

    The Mail Agent must never see Gmail, OAuth, IMAP or SMTP, and the Wiki Agent
    must never see Confluence: each reaches its system through an MCP tool and
    nothing else.
    """
    if module.agent_layer not in LAYERS_WITHOUT_SDKS:
        pytest.skip("adapter, composition root or server")

    violations = ENTERPRISE_SDK_ROOTS.intersection(module.imported_roots())

    assert not violations, f"{module.dotted_name} must not import external system SDK(s) {sorted(violations)}"


@pytest.mark.security
@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_business_code_ignores_the_runtime_transport(module: ModuleUnderTest):
    """No transport-free module names the serving side of the runtime.

    ``ygo74-agent-runtime`` is a foundation dependency: it owns the security
    model, the authenticated caller and the agent contracts, and naming it is
    expected. Its ``domains.endpoints`` package is a different matter - that is
    where FastAPI is imported - and a module that must run in a domain test with
    no web stack must not reach it.

    Before the security model moved into the library, this property held by
    construction because ``core`` imported no serving code at all. It now needs a
    test, and ``core`` is most of what that test exists for: ``core.serving`` is
    the one part allowed to know a transport, and every other part of ``core`` is
    not.
    """
    if not _must_avoid_the_transport(module):
        pytest.skip("adapter, composition root, serving module or server")

    violations = sorted(
        imported for imported in module.imported_modules() if imported.startswith(RUNTIME_TRANSPORT_MODULE)
    )

    assert not violations, f"{module.dotted_name} must not import the runtime transport: {violations}"


@pytest.mark.security
def test_a_domain_layer_runs_without_a_web_stack():
    """Importing the business layers must not drag a web framework in.

    The check above reads import statements, which is not the whole story: a
    package can pull a transport in through its own ``__init__``. That is exactly
    what the runtime used to do, so importing the permission model loaded FastAPI
    into a process that had no use for one.

    This test is the end-to-end version, and it is deliberately a subprocess: the
    test session itself exercises the HTTP surfaces, so ``fastapi`` is long since
    imported by the time this runs and an in-process assertion would be vacuous.
    """
    probe = textwrap.dedent(
        """
        import sys

        import ai_agent_lab.core.security.confirmation
        import ai_agent_lab.core.security.tickets
        import ai_agent_lab.mail.capabilities.write_capabilities
        import ai_agent_lab.mail.domain.models
        import ai_agent_lab.mail.skills.send_skill
        import ai_agent_lab.wiki.capabilities.write_capabilities
        import ai_agent_lab.wiki.domain.models
        import ai_agent_lab.wiki.skills.answer_skill

        loaded = sorted(name for name in sys.modules if name in {"fastapi", "starlette", "uvicorn"})
        print(",".join(loaded))
        """
    )

    finished = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPOSITORY_ROOT,
    )

    assert finished.stdout.strip() == "", f"a business layer pulled in a web stack: {finished.stdout.strip()}"


@pytest.mark.parametrize("namespace", NAMESPACES)
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
