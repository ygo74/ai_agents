"""Reading of the delivered skill and agent packages.

A skill package is a directory: ``skill.yaml`` declares the identity, the
security posture and the MCP tools the capability may use, and an optional
``SKILL.md`` carries the reasoning instructions of a capability driven by a
language model. A deterministic capability has no ``SKILL.md``: its substance is
code, and asking a model to reproduce it would trade correctness for prose.

Everything read here is validated on the way in. A manifest naming an unknown
permission, an unknown implementation or an operation weaker than the code
requires is refused, loudly, at load time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.manifests import AgentManifest, SkillManifest
from ai_agent_lab.core.security.floor import SecurityFloor
from ai_agent_lab.core.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.core.security.permissions import PermissionRegistry

SKILL_MANIFEST = "skill.yaml"
SKILL_PROMPT = "SKILL.md"
AGENT_MANIFEST = "agent.yaml"
AGENT_INSTRUCTIONS = "AGENT.md"

_SKILLS = "skills"
_AGENTS = "agents"


class ConfigurationError(DomainError):
    """Raised when delivered configuration cannot be turned into a manifest."""


class YamlDocument:
    """One YAML mapping read from disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = self._read(path)

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        """Parse a YAML mapping, refusing anything else."""
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ConfigurationError(f"could not read {path}: {error}") from error
        if not isinstance(loaded, dict):
            raise ConfigurationError(f"{path} must contain a mapping")
        return loaded

    def text(self, key: str) -> str:
        """Return a mandatory text field."""
        value = self._data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{self._path}: field {key!r} must be a non-empty string")
        return value.strip()

    def flag(self, key: str) -> bool:
        """Return a mandatory boolean field."""
        value = self._data.get(key)
        if not isinstance(value, bool):
            raise ConfigurationError(f"{self._path}: field {key!r} must be true or false")
        return value

    def texts(self, key: str) -> tuple[str, ...]:
        """Return an optional list of text values."""
        value = self._data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigurationError(f"{self._path}: field {key!r} must be a list of strings")
        return tuple(str(item) for item in value)

    def section(self, key: str) -> YamlSection:
        """Return a mandatory nested mapping."""
        value = self._data.get(key)
        if not isinstance(value, dict):
            raise ConfigurationError(f"{self._path}: field {key!r} must be a mapping")
        return YamlSection(self._path, key, value)


class YamlSection:
    """A nested mapping of a YAML document."""

    def __init__(self, path: Path, name: str, data: dict[str, Any]) -> None:
        self._path = path
        self._name = name
        self._data = data

    def text(self, key: str) -> str:
        """Return a mandatory text field of the section."""
        value = self._data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{self._path}: {self._name}.{key} must be a non-empty string")
        return value.strip()

    def flag(self, key: str) -> bool:
        """Return a mandatory boolean field of the section."""
        value = self._data.get(key)
        if not isinstance(value, bool):
            raise ConfigurationError(f"{self._path}: {self._name}.{key} must be true or false")
        return value


class SkillManifestLoader:
    """Turns one delivered skill package into a validated manifest."""

    def __init__(self, permissions: PermissionRegistry, floor: SecurityFloor) -> None:
        self._permissions = permissions
        self._floor = floor

    def load(self, package: Path) -> SkillManifest:
        """Read and validate the package of one capability."""
        document = YamlDocument(self._manifest_path(package))
        tool_name = document.text("tool_name")
        manifest = SkillManifest(
            tool_name=tool_name,
            implementation=document.text("implementation"),
            description=document.text("description"),
            operation=self._operation(document, tool_name),
            mcp_tools=document.texts("mcp_tools"),
            prompt=self._prompt(package),
        )
        self._floor.enforce(manifest.operation)
        return manifest

    @staticmethod
    def _manifest_path(package: Path) -> Path:
        """Return the manifest file of a package, or fail."""
        path = package / SKILL_MANIFEST
        if not path.is_file():
            raise ConfigurationError(f"skill package {package.name!r} has no {SKILL_MANIFEST}")
        return path

    @staticmethod
    def _prompt(package: Path) -> str:
        """Return the reasoning instructions, empty for a deterministic skill."""
        path = package / SKILL_PROMPT
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _operation(self, document: YamlDocument, tool_name: str) -> ToolOperationDescriptor:
        """Build the security metadata declared by a package."""
        section = document.section("operation")
        return ToolOperationDescriptor(
            tool_name=tool_name,
            operation_type=self._enum(OperationType, section.text("type"), "operation.type"),
            risk_level=self._enum(RiskLevel, section.text("risk"), "operation.risk"),
            required_permission=self._permissions.resolve(section.text("permission")),
            confirmation_required_by_default=section.flag("confirmation_required"),
        )

    @staticmethod
    def _enum[EnumT: (OperationType, RiskLevel)](
        enum_type: type[EnumT],
        value: str,
        field: str,
    ) -> EnumT:
        """Convert declared text into one of the accepted values."""
        try:
            return enum_type(value.upper())
        except ValueError as error:
            accepted = ", ".join(member.value for member in enum_type)
            raise ConfigurationError(f"{field} must be one of {accepted}, got {value!r}") from error


class AgentManifestLoader:
    """Assembles the manifest of an agent from its delivered configuration."""

    def __init__(self, directory: ConfigurationDirectory, skills: SkillManifestLoader) -> None:
        self._directory = directory
        self._skills = skills

    def load(self, agent: str) -> AgentManifest:
        """Read the identity, instructions and capabilities of an agent."""
        folder = self._directory.require(_AGENTS, agent)
        document = YamlDocument(folder / AGENT_MANIFEST)
        return AgentManifest(
            name=document.text("name"),
            description=document.text("description"),
            instructions=self._instructions(folder),
            skills=self._declared_skills(agent, document.texts("skills")),
        )

    @staticmethod
    def _instructions(folder: Path) -> str:
        """Return the system instructions delivered with the agent."""
        path = folder / AGENT_INSTRUCTIONS
        if not path.is_file():
            raise ConfigurationError(f"{folder} has no {AGENT_INSTRUCTIONS}")
        instructions = path.read_text(encoding="utf-8").strip()
        if not instructions:
            raise ConfigurationError(f"{path} is empty")
        return instructions

    def _declared_skills(self, agent: str, names: tuple[str, ...]) -> tuple[SkillManifest, ...]:
        """Load the packages the agent declares, in the declared order."""
        if not names:
            raise ConfigurationError(f"agent {agent!r} declares no skill")
        available = {package.name: package for package in self._directory.children(_SKILLS, agent)}
        return tuple(self._declared_skill(agent, name, available) for name in names)

    def _declared_skill(self, agent: str, name: str, available: dict[str, Path]) -> SkillManifest:
        """Load one declared package, or report what is available."""
        package = available.get(name)
        if package is None:
            known = ", ".join(sorted(available)) or "none"
            raise ConfigurationError(f"agent {agent!r} declares skill {name!r}; delivered packages: {known}")
        return self._skills.load(package)
