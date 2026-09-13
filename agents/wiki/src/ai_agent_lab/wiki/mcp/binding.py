"""Description of a deployed wiki MCP server.

Two servers never expose the same surface. `sooperset/mcp-atlassian` names its
tools `confluence_search` and `confluence_get_page`; a Notion server would have
its own names and its own gaps. Rather than pretend otherwise, a binding
declares:

- how to reach the server;
- which of our capabilities it can actually serve;
- the name it gives to each tool the dialect needs.

Anything a server does not declare is simply not offered to the model, instead of
failing on the first call.

A read-only deployment is expressed once, not twice. `read_only_variable` names
the environment variable that decides, and the same variable is what the binding
hands the server process in its `env:` block. When it is true the server exposes
no write tool, and the write capabilities declared below are withdrawn rather
than advertised.

Naming it in one place is the point. Declaring the writes in the binding while
telling the server to refuse them - two files, both plausible on their own - has
the agent promise an edit and then fail after the user has already approved it,
which is the exact failure this module exists to prevent.

Plugging a new wiki server is therefore a binding file plus a dialect class, and
no change to a skill or to the agent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.wiki.catalog import WikiToolCatalog, WikiToolName
from ai_agent_lab.wiki.wiki_errors import WikiToolProtocolError

MCP_DIRECTORY = "mcp"

# What a deployment must say to mean "this server accepts writes". Anything else
# - absent, misspelled, empty - reads as read-only.
#
# The asymmetry is deliberate. The question this answers is whether an agent may
# change a wiki a team relies on, and the only safe way to get "yes" is for
# somebody to have written it down unambiguously. A typo must cost a refusal,
# never an unintended edit.
_WRITABLE = frozenset({"0", "false", "no", "off"})


def is_read_only(value: str) -> bool:
    """Whether a deployment value leaves the server read-only."""
    return value.strip().casefold() not in _WRITABLE


class McpTransport(StrEnum):
    """How an MCP client reaches a wiki server."""

    STDIO = "stdio"
    HTTP = "http"


class McpBindingError(WikiToolProtocolError):
    """Raised when a delivered binding cannot be used as declared."""


class McpServerBinding:
    """What a deployed wiki MCP server offers, and how to reach it."""

    def __init__(
        self,
        *,
        server: str,
        transport: McpTransport,
        capabilities: Iterable[WikiToolName],
        tools: Mapping[str, str],
        dialect: str = "native",
        url: str = "",
        command: str = "",
        args: Iterable[str] = (),
        env: Mapping[str, str] | None = None,
        read_only_variable: str = "",
    ) -> None:
        self._server = server
        self._transport = transport
        self._capabilities = frozenset(capabilities)
        self._tools = dict(tools)
        self._dialect = dialect
        self._url = url
        self._command = command
        self._args = tuple(args)
        self._env = dict(env or {})
        self._read_only_variable = read_only_variable

    @property
    def server(self) -> str:
        """Name of the bound server."""
        return self._server

    @property
    def dialect(self) -> str:
        """Which client speaks to this server.

        ``native`` means the server answers our own tool names with the contract
        payloads and needs no translation.
        """
        return self._dialect

    @property
    def transport(self) -> McpTransport:
        """How the client reaches the server."""
        return self._transport

    @property
    def url(self) -> str:
        """Endpoint of an HTTP server."""
        return self._url

    @property
    def command(self) -> str:
        """Executable of a stdio server."""
        return self._command

    @property
    def args(self) -> tuple[str, ...]:
        """Arguments of a stdio server."""
        return self._args

    @property
    def env(self) -> Mapping[str, str]:
        """Environment variable names the server process needs, and their source.

        Values are never written here. A binding names the variable a value comes
        from - ``CONFLUENCE_API_TOKEN`` - and the value is read from the ambient
        environment when the process starts. A credential in a delivered file
        would be a credential in version control.
        """
        return dict(self._env)

    @property
    def capabilities(self) -> frozenset[WikiToolName]:
        """Capabilities this server declares it can serve.

        What the file says, before a deployment has been taken into account. Use
        :meth:`capabilities_in` to know what is actually offered.
        """
        return self._capabilities

    @property
    def read_only_variable(self) -> str:
        """Environment variable deciding whether this server accepts writes."""
        return self._read_only_variable

    def capabilities_in(self, environment: Mapping[str, str]) -> frozenset[WikiToolName]:
        """Capabilities this server serves in a given deployment.

        A server told to be read-only exposes no write tool at all, so offering
        one to the model would be advertising something that cannot happen. The
        write capabilities are withdrawn instead, and the agent says plainly that
        it cannot change this wiki rather than proposing an edit and failing.

        A binding that names no variable is unaffected: it has no read-only mode
        to speak of.

        An unset or unrecognised value reads as read-only. Somebody has to say
        plainly that this agent may write to a wiki; a missing variable is not
        somebody saying it.
        """
        if not self._read_only_variable:
            return self._capabilities
        if not is_read_only(environment.get(self._read_only_variable, "")):
            return self._capabilities
        catalog = WikiToolCatalog()
        return frozenset(
            capability
            for capability in self._capabilities
            if not catalog.descriptor(capability).is_write
        )

    def supports(self, capability: WikiToolName) -> bool:
        """Whether the server declares it can serve a capability."""
        return capability in self._capabilities

    def remote(self, alias: str) -> str:
        """Return the name this server gives to a tool the dialect needs."""
        remote = self._tools.get(alias)
        if remote is None:
            raise McpBindingError(f"server {self._server!r} declares no tool named {alias!r}")
        return remote

    def require_aliases(self, aliases: Iterable[str]) -> None:
        """Fail now when the dialect needs a tool the binding never named."""
        missing = sorted(alias for alias in aliases if alias not in self._tools)
        if missing:
            raise McpBindingError(f"server {self._server!r} is missing tool names {missing}")

    def require_declared_capabilities(self) -> None:
        """Fail now when a declared capability has no tool behind it.

        A binding that offers ``update_page`` without naming the tool that
        performs it would advertise the capability to the model and fail on the
        first call - after the user had already confirmed a write.
        """
        undeclared = sorted(
            capability.value for capability in self._capabilities if capability.value not in self._tools
        )
        if undeclared:
            raise McpBindingError(
                f"server {self._server!r} declares capabilities {undeclared} but names no tool for them"
            )


class McpServerBindingLoader:
    """Reads and validates the binding delivered for a wiki MCP server."""

    def __init__(self, directory: ConfigurationDirectory) -> None:
        self._directory = directory

    def load(self, name: str) -> McpServerBinding:
        """Read the binding of one server."""
        path = self._directory.require(MCP_DIRECTORY, f"{name}.yaml")
        document = self._document(path)
        binding = McpServerBinding(
            server=str(document.get("server", name)),
            transport=self._transport(document, path),
            capabilities=self._capabilities(document, path),
            tools=self._tools(document, path),
            dialect=str(document.get("dialect", "native")).strip() or "native",
            url=str(document.get("url", "")).strip(),
            command=str(document.get("command", "")).strip(),
            args=tuple(str(item) for item in self._list(document, "args", path)),
            env=self._env(document, path),
            read_only_variable=str(document.get("read_only_variable", "")).strip(),
        )
        self._require_endpoint(binding, path)
        return binding

    @staticmethod
    def _document(path: Path) -> dict[str, Any]:
        """Parse the binding file, refusing anything but a mapping."""
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise McpBindingError(f"could not read {path}: {error}") from error
        if not isinstance(document, dict):
            raise McpBindingError(f"{path} must contain a mapping")
        return document

    @staticmethod
    def _transport(document: dict[str, Any], path: Path) -> McpTransport:
        """Return the declared transport."""
        declared = str(document.get("transport", "")).strip().lower()
        try:
            return McpTransport(declared)
        except ValueError as error:
            accepted = ", ".join(member.value for member in McpTransport)
            raise McpBindingError(f"{path}: 'transport' must be one of {accepted}, got {declared!r}") from error

    @staticmethod
    def _list(document: dict[str, Any], key: str, path: Path) -> list[Any]:
        """Return an optional list field."""
        value = document.get(key, [])
        if not isinstance(value, list):
            raise McpBindingError(f"{path}: field {key!r} must be a list")
        return value

    def _capabilities(self, document: dict[str, Any], path: Path) -> frozenset[WikiToolName]:
        """Return the catalogued capabilities the server declares."""
        declared = self._list(document, "capabilities", path)
        if not declared:
            raise McpBindingError(f"{path}: 'capabilities' must list at least one capability")
        known = {name.value: name for name in WikiToolName}
        unknown = sorted(str(item) for item in declared if str(item) not in known)
        if unknown:
            raise McpBindingError(f"{path}: unknown capabilities {unknown}")
        return frozenset(known[str(item)] for item in declared)

    @staticmethod
    def _tools(document: dict[str, Any], path: Path) -> dict[str, str]:
        """Return the alias to remote-name correspondence."""
        declared = document.get("tools")
        if not isinstance(declared, dict) or not declared:
            raise McpBindingError(f"{path}: field 'tools' must be a non-empty mapping")
        invalid = [key for key, value in declared.items() if not isinstance(value, str) or not value.strip()]
        if invalid:
            raise McpBindingError(f"{path}: tools {sorted(invalid)} must map to non-empty names")
        return {str(key): str(value).strip() for key, value in declared.items()}

    @staticmethod
    def _env(document: dict[str, Any], path: Path) -> dict[str, str]:
        """Return the environment variables a stdio server needs.

        Only names are accepted. A value that looks like a credential is refused
        outright rather than tidied up, because a binding is a delivered file and
        delivered files are committed.
        """
        declared = document.get("env", {})
        if not isinstance(declared, dict):
            raise McpBindingError(f"{path}: field 'env' must be a mapping")
        invalid = [key for key, value in declared.items() if not isinstance(value, str)]
        if invalid:
            raise McpBindingError(f"{path}: env entries {sorted(invalid)} must map to strings")
        return {str(key): str(value) for key, value in declared.items()}

    @staticmethod
    def _require_endpoint(binding: McpServerBinding, path: Path) -> None:
        """Refuse a binding that does not say where the server lives."""
        if binding.transport is McpTransport.HTTP and not binding.url:
            raise McpBindingError(f"{path}: an http server requires 'url'")
        if binding.transport is McpTransport.STDIO and not binding.command:
            raise McpBindingError(f"{path}: a stdio server requires 'command'")
        binding.require_declared_capabilities()
