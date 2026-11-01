"""Mail and Wiki select delivered configuration at load time, without copying shared files."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from ygo74.agent_runtime.domains.configuration.directory import ConfigurationNotFoundError
from ygo74.agent_runtime.domains.configuration.manifests import ConfigurationError

from ai_agent_lab.mail.bootstrap.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.infrastructure.configuration.environment import MailEnvironmentFile
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentSettings
from ai_agent_lab.wiki.bootstrap.composition import WikiAgentCompositionRoot
from ai_agent_lab.wiki.infrastructure.configuration.environment import WikiEnvironmentFile
from ai_agent_lab.wiki.infrastructure.configuration.settings import WikiAgentSettings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["mail", "wiki"])
def agent_configuration(request, tmp_path, monkeypatch):
    """Provide each composition root with isolated delivered configuration."""
    for name in ("AGENT_CONFIG_SUBDIR", "AGENT_MANIFEST_FILENAME"):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "config"
    shutil.copytree(ROOT / "config", config)
    monkeypatch.setenv("YGO74_AGENT_RUNTIME_CONFIG_DIR", str(config))
    agent = request.param
    if agent == "mail":
        root = MailAgentCompositionRoot(MailAgentSettings(_env_file=None), Mock())
    else:
        root = WikiAgentCompositionRoot(WikiAgentSettings(_env_file=None), Mock())
    return agent, config, root


@pytest.mark.parametrize("value", [None, "", "   "])
def test_default_manifest_selection(agent_configuration, monkeypatch, value):
    """Absent or empty selectors retain the delivered agent and skills."""
    agent, _, root = agent_configuration
    if value is not None:
        monkeypatch.setenv("AGENT_CONFIG_SUBDIR", value)
        monkeypatch.setenv("AGENT_MANIFEST_FILENAME", value)

    manifest = root.manifest()

    assert manifest.name == f"{agent}-agent"
    assert manifest.skills


@pytest.mark.parametrize("custom_subdir", [False, True])
@pytest.mark.parametrize("custom_filename", [False, True])
def test_manifest_selectors_are_independent(agent_configuration, monkeypatch, custom_subdir, custom_filename):
    """A filename variant shares instructions and skills; a full variant selects both trees."""
    agent, config, root = agent_configuration
    baseline = root.manifest()
    selected = agent
    if custom_subdir:
        selected = f"{agent}-variant"
        shutil.copytree(config / "agents" / agent, config / "agents" / selected)
        shutil.copytree(config / "skills" / agent, config / "skills" / selected)
        monkeypatch.setenv("AGENT_CONFIG_SUBDIR", selected)
    filename = "agent.variant.yaml" if custom_filename else "agent.yaml"
    folder = config / "agents" / selected
    source = yaml.safe_load((folder / "agent.yaml").read_text(encoding="utf-8"))
    source["description"] = "Selected configuration variant."
    (folder / filename).write_text(yaml.safe_dump(source), encoding="utf-8")
    if custom_filename:
        monkeypatch.setenv("AGENT_MANIFEST_FILENAME", filename)

    manifest = root.manifest()

    assert manifest.description == "Selected configuration variant."
    assert manifest.instructions == baseline.instructions
    assert manifest.skills == baseline.skills
    assert manifest.mcp_server == baseline.mcp_server


def test_selectors_from_environment_file_are_loaded_after_import(agent_configuration, tmp_path, monkeypatch):
    """Launcher environment files can select a manifest after composition modules are imported."""
    agent, config, root = agent_configuration
    monkeypatch.setattr(os, "environ", os.environ.copy())
    folder = config / "agents" / agent
    source = yaml.safe_load((folder / "agent.yaml").read_text(encoding="utf-8"))
    source["description"] = "Configuration selected from the environment file."
    (folder / "agent.local.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    selected = tmp_path / "selected.env"
    selected.write_text(f"AGENT_CONFIG_SUBDIR={agent}\nAGENT_MANIFEST_FILENAME=agent.local.yaml\n", encoding="utf-8")
    environment = MailEnvironmentFile() if agent == "mail" else WikiEnvironmentFile()

    environment.load(selected)

    assert root.manifest().description == "Configuration selected from the environment file."


def test_missing_selected_manifest_fails(agent_configuration, monkeypatch):
    """An explicitly selected missing file must not silently fall back to agent.yaml."""
    _, _, root = agent_configuration
    monkeypatch.setenv("AGENT_MANIFEST_FILENAME", "missing.yaml")

    with pytest.raises(ConfigurationError, match=r"missing\.yaml"):
        root.manifest()


def test_invalid_selected_manifest_fails(agent_configuration, monkeypatch):
    """Selected variants must satisfy the same strict schema as the default manifest."""
    agent, config, root = agent_configuration
    (config / "agents" / agent / "invalid.yaml").write_text("unexpected_field: rejected\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MANIFEST_FILENAME", "invalid.yaml")

    with pytest.raises(ConfigurationError, match=r"invalid\.yaml"):
        root.manifest()


def test_missing_selected_subdir_fails(agent_configuration, monkeypatch):
    """An explicitly selected missing configuration tree fails clearly."""
    _, _, root = agent_configuration
    monkeypatch.setenv("AGENT_CONFIG_SUBDIR", "missing-variant")

    with pytest.raises(ConfigurationNotFoundError, match="missing-variant"):
        root.manifest()
