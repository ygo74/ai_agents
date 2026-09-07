"""Description of a deployed mail MCP server.

Two servers never expose the same surface. The official Gmail server has no
send tool and no per-message retrieval; a server built on EWS will have its own
gaps and its own names. Rather than pretend otherwise, a binding declares:

- how to reach the server;
- which of our capabilities it can actually serve;
- the name it gives to each tool the dialect needs.

Anything a server does not declare is simply not offered to the model, instead
of failing on the first call. Plugging a new mail server is therefore a binding
file plus a dialect class, and no change to a skill or to the agent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from ai_agent_lab.infrastructure.config.directory import ConfigurationDirectory
from ai_agent_lab.infrastructure.config.settings import McpTransport
from ai_agent_lab.mcp.mail.catalog import MailToolName
from ai_agent_lab.mcp.mail.errors import MailToolProtocolError

MCP_DIRECTORY = "mcp"


class McpBindingError(MailToolProtocolError):
    """Raised when a delivered binding cannot be used as declared."""


class McpServerBinding:
    """What a deployed mail MCP server offers, and how to reach it."""

    def __init__(
        self,
        *,
        server: str,
        transport: McpTransport,
        capabilities: Iterable[MailToolName],
        tools: Mapping[str, str],
        dialect: str = "native",
        url: str = "",
        command: str = "",
        args: Iterable[str] = (),
    ) -> None:
        self._server = server
        self._transport = transport
        self._capabilities = frozenset(capabilities)
        self._tools = dict(tools)
        self._dialect = dialect
        self._url = url
        self._command = command
        self._args = tuple(args)

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
    def capabilities(self) -> frozenset[MailToolName]:
        """Capabilities this server declares it can serve."""
        return self._capabilities

    def supports(self, capability: MailToolName) -> bool:
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


class McpServerBindingLoader:
    """Reads and validates the binding delivered for a mail MCP server."""

    def __init__(self, directory: ConfigurationDirectory) -> None:
        self._directory = directory

    def load(self, name: str) -> McpServerBinding:
        """Read the binding of one server."""
        path = self._directory.require(MCP_DIRECTORY, f"{name}.yaml")
        document = self._document(path)
        transport = self._transport(document, path)
        binding = McpServerBinding(
            server=str(document.get("server", name)),
            transport=transport,
            capabilities=self._capabilities(document, path),
            tools=self._tools(document, path),
            dialect=str(document.get("dialect", "native")).strip() or "native",
            url=str(document.get("url", "")).strip(),
            command=str(document.get("command", "")).strip(),
            args=tuple(str(item) for item in self._list(document, "args", path)),
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

    def _capabilities(self, document: dict[str, Any], path: Path) -> frozenset[MailToolName]:
        """Return the catalogued capabilities the server declares."""
        declared = self._list(document, "capabilities", path)
        if not declared:
            raise McpBindingError(f"{path}: 'capabilities' must list at least one capability")
        known = {name.value: name for name in MailToolName}
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
    def _require_endpoint(binding: McpServerBinding, path: Path) -> None:
        """Refuse a binding that does not say where the server lives."""
        if binding.transport is McpTransport.HTTP and not binding.url:
            raise McpBindingError(f"{path}: an http server requires 'url'")
        if binding.transport is McpTransport.STDIO and not binding.command:
            raise McpBindingError(f"{path}: a stdio server requires 'command'")
