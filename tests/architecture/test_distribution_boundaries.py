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
import importlib.util
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

# Agent code may depend on the language-neutral runtime domains it uses, but
# `core` is deliberately much smaller after the extraction and must not regain
# the configuration, security or reasoning layers.
ALLOWED_RUNTIME_IMPORTS: dict[str, tuple[str, ...]] = {
    "ai_agent_lab.core": ("ygo74.agent_runtime.domains.errors",),
    "ai_agent_lab.maf": (
        "ygo74.agent_runtime.domains.contracts",
        "ygo74.agent_runtime.domains.errors",
        "ygo74.agent_runtime.domains.humanapproval",
        "ygo74.agent_runtime.domains.reasoning",
        "ygo74.agent_runtime.domains.security",
    ),
    "ai_agent_lab.langgraph": (
        "ygo74.agent_runtime.domains.contracts",
        "ygo74.agent_runtime.domains.errors",
        "ygo74.agent_runtime.domains.humanapproval",
        "ygo74.agent_runtime.domains.reasoning",
        "ygo74.agent_runtime.domains.security",
    ),
    "ai_agent_lab.mail": (
        "ygo74.agent_runtime.domains.auth",
        "ygo74.agent_runtime.domains.configuration",
        "ygo74.agent_runtime.domains.contracts",
        "ygo74.agent_runtime.domains.discovery",
        "ygo74.agent_runtime.domains.endpoints",
        "ygo74.agent_runtime.domains.errors",
        "ygo74.agent_runtime.domains.http",
        "ygo74.agent_runtime.domains.humanapproval",
        "ygo74.agent_runtime.domains.mcp",
        "ygo74.agent_runtime.domains.reasoning",
        "ygo74.agent_runtime.domains.security",
        "ygo74.agent_runtime.domains.sessions",
    ),
    "ai_agent_lab.wiki": (
        "ygo74.agent_runtime.domains.auth",
        "ygo74.agent_runtime.domains.configuration",
        "ygo74.agent_runtime.domains.contracts",
        "ygo74.agent_runtime.domains.discovery",
        "ygo74.agent_runtime.domains.endpoints",
        "ygo74.agent_runtime.domains.errors",
        "ygo74.agent_runtime.domains.http",
        "ygo74.agent_runtime.domains.humanapproval",
        "ygo74.agent_runtime.domains.mcp",
        "ygo74.agent_runtime.domains.reasoning",
        "ygo74.agent_runtime.domains.security",
        "ygo74.agent_runtime.domains.sessions",
    ),
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

MAIL_LAYERS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "application": frozenset({"domain"}),
    "infrastructure": frozenset({"domain", "application"}),
    "adapters": frozenset({"domain", "application", "infrastructure", "bootstrap"}),
    "bootstrap": frozenset({"domain", "application", "infrastructure", "adapters"}),
}
WIKI_LAYERS = MAIL_LAYERS
AGENT_LAYERS = {
    "ai_agent_lab.mail": MAIL_LAYERS,
    "ai_agent_lab.wiki": WIKI_LAYERS,
}
MAIL_REMOVED_APPLICATION_MODULES = frozenset(
    f"ai_agent_lab.mail.application.{name}"
    for name in ("__main__", "cli_entrypoint", "native", "authorise", "discover", "entrypoints", "approval")
)

# Agent-specific modules now live in their declared layers rather than directly
# below the package root.
AGENT_ROOT_MODULES = frozenset()

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
LAYERS_WITHOUT_FRAMEWORKS = {
    "ai_agent_lab.mail": frozenset({"domain", "application", "infrastructure"}),
    "ai_agent_lab.wiki": frozenset({"domain", "application", "infrastructure"}),
}

# Agent layers that must not name a transport or a vendor SDK. `mcp` is excluded:
# the dialects are the adapters, and speaking MCP is their job.
LAYERS_WITHOUT_SDKS = {
    "ai_agent_lab.mail": frozenset({"domain", "application"}),
    "ai_agent_lab.wiki": frozenset({"domain", "application"}),
}

# `ygo74-agent-runtime` is a foundation dependency now that it owns the security
# model and the agent contracts, so naming it is not in itself a layer violation.
# One of its domains is a transport all the same: `domains.endpoints` is where
# FastAPI lives. A module that must stay free of a transport must stay free of
# that domain, which is what this prefix pins. Without it, the property the layers
# used to have by construction - `core` knew no web stack - would be gone with no
# test to notice.
RUNTIME_TRANSPORT_MODULE = "ygo74.agent_runtime.domains.endpoints"

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
        if self.distribution == "ai_agent_lab.wiki" and head in AGENT_ROOT_MODULES:
            return None
        return head

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
        """Resolve imports, including package aliases and relative imports.

        Imported names may be symbols rather than modules. Keeping both the
        source and its aliases closes ``from package import forbidden_layer``
        without needing to import production code during collection.
        """
        package = self.dotted_name if self._path.name == "__init__.py" else self.dotted_name.rpartition(".")[0]
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                source = node.module or ""
                if node.level:
                    source = importlib.util.resolve_name("." * node.level + source, package)
                if source:
                    yield source
                    yield from (f"{source}.{alias.name}" for alias in node.names if alias.name != "*")


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

    Two families qualify: the business layers of an agent, and every module in
    the framework-free core distribution.
    """
    if module.distribution == "ai_agent_lab.core":
        return True
    return module.agent_layer in LAYERS_WITHOUT_SDKS.get(module.distribution, ())


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


@pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
def test_agent_runtime_imports_stay_within_the_declared_domains(module: ModuleUnderTest):
    """Each agent distribution names only the runtime domains it consumes."""
    if module.distribution not in ALLOWED_RUNTIME_IMPORTS:
        pytest.skip("not an agent distribution")
    allowed = ALLOWED_RUNTIME_IMPORTS.get(module.distribution, ())
    violations = {
        imported
        for imported in module.imported_modules()
        if imported.startswith("ygo74.agent_runtime.domains.")
        and not any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in allowed)
    }

    assert not violations, f"{module.dotted_name} must not import runtime domain(s) {sorted(violations)}"


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
    layers = AGENT_LAYERS[module.distribution]
    assert layer in layers, f"{module.dotted_name} sits outside the declared layers"
    allowed = layers[layer] | {layer}
    if module.distribution == "ai_agent_lab.wiki":
        allowed |= AGENT_ROOT_MODULES
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

    assert layer in AGENT_LAYERS[module.distribution], f"{module.dotted_name} sits outside the declared layers"


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
    if module.agent_layer is not None and module.agent_layer not in LAYERS_WITHOUT_FRAMEWORKS.get(
        module.distribution, ()
    ):
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
    if module.agent_layer not in LAYERS_WITHOUT_SDKS.get(module.distribution, ()):
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

    The shared configuration and domain code imports the runtime, but it must
    remain independent from the runtime's FastAPI endpoint adapters.
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

        import ygo74.agent_runtime.domains.humanapproval.confirmation
        import ygo74.agent_runtime.domains.humanapproval.tickets
        import ai_agent_lab.mail.adapters.capabilities.write_capabilities
        import ai_agent_lab.mail.domain.models
        import ai_agent_lab.mail.application.skills.send_skill
        import ai_agent_lab.wiki.adapters.capabilities.write_capabilities
        import ai_agent_lab.wiki.domain.models
        import ai_agent_lab.wiki.application.skills.answer_skill

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


MAIL = "ai_agent_lab.mail"
MAIL_BOOTSTRAP_IMPORTS = {
    f"{MAIL}.adapters.cli.entrypoint": frozenset({f"{MAIL}.bootstrap.composition", f"{MAIL}.bootstrap.factory"}),
    f"{MAIL}.adapters.cli.authorise": frozenset({f"{MAIL}.bootstrap.mail_tools_provider"}),
    f"{MAIL}.adapters.http.entrypoint": frozenset({f"{MAIL}.bootstrap.conversation"}),
    f"{MAIL}.adapters.maf.native": frozenset({f"{MAIL}.bootstrap.factory"}),
    f"{MAIL}.adapters.maf.session": frozenset({f"{MAIL}.bootstrap.composition"}),
}
MAIL_NEUTRAL_RUNTIME_IMPORTS = {
    "domain": (
        "ygo74.agent_runtime.domains.errors",
        "ygo74.agent_runtime.domains.security",
    ),
    "application": (
        "ygo74.agent_runtime.domains.errors",
        "ygo74.agent_runtime.domains.security",
        "ygo74.agent_runtime.domains.reasoning",
        "ygo74.agent_runtime.domains.humanapproval",
        "ygo74.agent_runtime.domains.contracts",
    ),
}


def _within(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


@pytest.mark.parametrize("module", _of(MAIL), ids=lambda module: module.dotted_name)
def test_mail_inner_layers_only_import_neutral_dependencies(module: ModuleUnderTest):
    if module.agent_layer not in MAIL_NEUTRAL_RUNTIME_IMPORTS:
        pytest.skip("outer Mail module")
    allowed = (
        f"{MAIL}.domain",
        *MAIL_NEUTRAL_RUNTIME_IMPORTS[module.agent_layer],
        "pydantic",
    )
    if module.agent_layer == "application":
        allowed += (f"{MAIL}.application",)
    violations = {
        name
        for name in module.imported_modules()
        if name.split(".", 1)[0] not in sys.stdlib_module_names and not any(_within(name, prefix) for prefix in allowed)
    }
    assert not violations, f"{module.dotted_name} imports non-neutral dependencies: {sorted(violations)}"


@pytest.mark.parametrize("module", _of(MAIL), ids=lambda module: module.dotted_name)
def test_mail_canonical_modules_never_import_legacy_paths(module: ModuleUnderTest):
    violations = {
        name
        for name in module.imported_modules()
        if any(_within(name, prefix) for prefix in MAIL_REMOVED_APPLICATION_MODULES)
    }
    assert not violations, f"{module.dotted_name} imports legacy Mail paths: {sorted(violations)}"


@pytest.mark.parametrize("module", _of(MAIL), ids=lambda module: module.dotted_name)
def test_mail_adapters_only_reach_named_bootstrap_entrypoints(module: ModuleUnderTest):
    if module.agent_layer != "adapters":
        pytest.skip("not a Mail adapter")
    allowed = MAIL_BOOTSTRAP_IMPORTS.get(module.dotted_name, ())
    violations = {
        name
        for name in module.imported_modules()
        if _within(name, f"{MAIL}.bootstrap") and not any(_within(name, prefix) for prefix in allowed)
    }
    assert not violations, f"{module.dotted_name} reaches bootstrap outside its entrypoint: {sorted(violations)}"


def test_mail_root_cannot_regain_business_implementations():
    root = DISTRIBUTIONS[MAIL].joinpath(*MAIL.split("."))
    assert sorted(path.name for path in root.glob("*.py")) == ["__init__.py"]
    tree = ast.parse((root / "__init__.py").read_text(encoding="utf-8"))
    assert all(
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for node in tree.body
    ), "Mail's root initializer must not import or implement business behavior"


@pytest.mark.parametrize("name", sorted(MAIL_REMOVED_APPLICATION_MODULES))
def test_mail_has_no_legacy_entrypoints_or_packages(name: str):
    root = DISTRIBUTIONS[MAIL]
    path = root.joinpath(*name.split("."))
    assert not path.with_suffix(".py").exists(), f"obsolete Mail module: {name}"
    assert not path.is_dir(), f"obsolete Mail package: {name}"


@pytest.mark.parametrize("module", _of("ai_agent_lab.maf"), ids=lambda module: module.dotted_name)
def test_generic_maf_never_imports_mail(module: ModuleUnderTest):
    assert not any(_within(name, MAIL) for name in module.imported_modules()), module.dotted_name


@pytest.mark.parametrize("module", _of(MAIL), ids=lambda module: module.dotted_name)
def test_mail_inner_layers_do_not_reach_framework_adapters(module: ModuleUnderTest):
    if module.agent_layer not in {"domain", "application", "infrastructure"}:
        pytest.skip("outer Mail module")
    forbidden = (*FRAMEWORK_ADAPTERS, "ygo74.agent_runtime.integrations")
    violations = {name for name in module.imported_modules() if any(_within(name, prefix) for prefix in forbidden)}
    assert not violations, f"{module.dotted_name} reaches a framework adapter: {sorted(violations)}"


@pytest.mark.parametrize(
    ("class_name", "owner"),
    [
        ("ReplyRecipientPlanner", f"{MAIL}.domain.services.reply_recipient_planner"),
        ("MailToolName", f"{MAIL}.domain.operation_names"),
        ("MailSecurityFloor", f"{MAIL}.domain.policies.security_floor"),
        ("MailToolCatalog", f"{MAIL}.application.operations"),
        ("MailSkills", f"{MAIL}.application.skills.bundle"),
        ("MailTools", f"{MAIL}.application.ports.mail_tools"),
        ("MailConfirmationPresenter", f"{MAIL}.application.confirmations.presenter"),
        ("DeliveredMailOperations", f"{MAIL}.infrastructure.configuration.operations"),
    ],
)
def test_mail_business_components_have_one_canonical_owner(class_name: str, owner: str):
    definitions = [
        module.dotted_name
        for module in _of(MAIL)
        for node in ast.walk(module._tree)
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    assert definitions == [owner], f"{class_name} belongs exclusively to {owner}, found {definitions}"


def _synthetic_module(source: str, relative_path: str) -> ModuleUnderTest:
    module = ModuleUnderTest.__new__(ModuleUnderTest)
    module.distribution = MAIL
    module._source_root = DISTRIBUTIONS[MAIL]
    module._path = module._source_root.joinpath(*MAIL.split("."), *relative_path.split(".")).with_suffix(".py")
    module._tree = ast.parse(source)
    return module


@pytest.mark.parametrize(
    ("source", "path", "expected"),
    [
        ("from ..infrastructure import mcp as transport", "application.example", f"{MAIL}.infrastructure.mcp"),
        ("from . import skills as processing", "application.example", f"{MAIL}.application.skills"),
        ("from . import skills", "application.__init__", f"{MAIL}.application.skills"),
        ("from ... import maf as framework", "application.example", "ai_agent_lab.maf"),
        ("from ai_agent_lab import maf", "application.example", "ai_agent_lab.maf"),
        ("from ai_agent_lab.mail import infrastructure", "application.example", f"{MAIL}.infrastructure"),
        ("from .. import operations", "application.skills.example", f"{MAIL}.application.operations"),
        ("from ....mail import domain", "application.skills.example", f"{MAIL}.domain"),
    ],
)
def test_import_reader_resolves_relative_and_package_aliases(source: str, path: str, expected: str):
    module = _synthetic_module(source, path)
    assert expected in set(module.imported_modules())


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("from .. import application", "domain.example"),
        ("from ...adapters import capabilities", "application.skills.example"),
        ("from ai_agent_lab.mail import bootstrap as composition", "application.example"),
    ],
)
def test_import_reader_cannot_hide_outward_dependencies(source: str, path: str):
    module = _synthetic_module(source, path)
    with pytest.raises(AssertionError, match="must not import layer"):
        test_agent_layers_point_inwards(module)


def test_import_reader_cannot_hide_a_framework_distribution():
    module = _synthetic_module("from ... import maf as framework", "application.example")
    assert "ai_agent_lab.maf" in set(module.imported_distributions())
    with pytest.raises(AssertionError, match="non-neutral dependencies"):
        test_mail_inner_layers_only_import_neutral_dependencies(module)


def _run_mail_import_probe(code: str) -> None:
    finished = subprocess.run(  # noqa: S603 - fixed source, no shell
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        timeout=60,
        check=False,
    )
    assert finished.returncode == 0, f"Mail import probe failed:\n{finished.stdout}\n{finished.stderr}"


@pytest.mark.security
@pytest.mark.parametrize("layer", ["domain", "application"])
def test_mail_inner_layer_imports_without_framework_or_web_stack(layer: str):
    names = [
        module.dotted_name for module in _of(MAIL) if module.agent_layer == layer
    ]
    _run_mail_import_probe(
        textwrap.dedent(
            f"""
            import importlib
            import importlib.abc
            import sys
            sys.path.insert(0, {str(DISTRIBUTIONS[MAIL])!r})
            blocked = {{"agent_framework", "ai_agent_lab.maf", "fastapi", "starlette", "uvicorn",
                        "langchain", "langchain_core", "langgraph", "crewai"}}
            class BlockOuterDependencies(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
                        raise ModuleNotFoundError("inner Mail layer imported " + fullname, name=fullname)
            sys.meta_path.insert(0, BlockOuterDependencies())
            for name in {names!r}:
                importlib.import_module(name)
            assert not any(
                loaded == name or loaded.startswith(name + ".")
                for loaded in sys.modules for name in blocked
            )
            """
        )
    )


@pytest.mark.security
@pytest.mark.parametrize("missing_package", ["mail_mcp", "mail_mcp.protocol"])
def test_gmail_dialect_imports_without_the_optional_native_protocol(missing_package: str):
    _run_mail_import_probe(
        textwrap.dedent(
            f"""
            import importlib.abc
            import sys
            from pathlib import Path
            sys.path.insert(0, {str(DISTRIBUTIONS[MAIL])!r})
            class NoNativeProtocol(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == {missing_package!r} or fullname.startswith({missing_package!r} + "."):
                        raise ModuleNotFoundError("native protocol is not installed", name=fullname)
            sys.meta_path.insert(0, NoNativeProtocol())
            from ai_agent_lab.mail.application.errors import MailToolUnavailableError
            from ai_agent_lab.mail.infrastructure.mcp.google.client import GmailMailTools
            from ai_agent_lab.mail.infrastructure.mcp.configuration import load_binding
            from ai_agent_lab.mail.infrastructure.mcp.dialects import create_dialect_registry
            from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
            registry = create_dialect_registry()
            binding = load_binding(ConfigurationDirectory(Path.cwd() / "config"), "gmail")
            client = registry.build(binding, object(), "architecture@example.test")
            assert isinstance(client, GmailMailTools)
            assert not any(
                name == "mail_mcp.protocol" or name.startswith("mail_mcp.protocol.")
                for name in sys.modules
            )
            assert "ai_agent_lab.mail.infrastructure.mcp.native.client" not in sys.modules
            native_binding = load_binding(ConfigurationDirectory(Path.cwd() / "config"), "local")
            try:
                registry.build(native_binding, object(), "architecture@example.test")
            except MailToolUnavailableError as error:
                assert "ai-agent-lab-mail-agent[native]" in str(error)
                assert isinstance(error.__cause__, ModuleNotFoundError)
                assert error.__cause__.name == {missing_package!r}
            else:
                raise AssertionError("native selection must explain the missing optional dependency")
            assert isinstance(registry.build(binding, object(), "architecture@example.test"), GmailMailTools)
            """
        )
    )


def test_native_dialect_does_not_misreport_unrelated_missing_dependencies():
    _run_mail_import_probe(
        textwrap.dedent(
            f"""
            import importlib.abc
            import sys
            from pathlib import Path
            sys.path.insert(0, {str(DISTRIBUTIONS[MAIL])!r})
            class BrokenNativeDependency(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "ai_agent_lab.mail.infrastructure.mcp.native.client":
                        raise ModuleNotFoundError("unrelated dependency is missing", name="unrelated_dependency")
            sys.meta_path.insert(0, BrokenNativeDependency())
            from ai_agent_lab.mail.infrastructure.mcp.configuration import load_binding
            from ai_agent_lab.mail.infrastructure.mcp.dialects import create_dialect_registry
            from ygo74.agent_runtime.domains.configuration.directory import ConfigurationDirectory
            binding = load_binding(ConfigurationDirectory(Path.cwd() / "config"), "local")
            try:
                create_dialect_registry().build(binding, object(), "architecture@example.test")
            except ModuleNotFoundError as error:
                assert error.name == "unrelated_dependency"
            else:
                raise AssertionError("an unrelated import failure must not be hidden")
            """
        )
    )
