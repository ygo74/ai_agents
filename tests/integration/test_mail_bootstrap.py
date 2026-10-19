"""Shared composition and canonical executable paths preserve host behavior."""

import importlib
from pathlib import Path
from unittest.mock import Mock

import pytest
from tests.support.maf_fakes import ScriptedChatClient, says
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal

from ai_agent_lab.mail.bootstrap.chat_client import ConfiguredChatClientFactory
from ai_agent_lab.mail.bootstrap.factory import MailAgentApplicationFactory
from ai_agent_lab.mail.infrastructure.configuration.settings import MailAgentSettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


async def test_factory_preserves_injected_client_settings_and_principal():
    client = ScriptedChatClient([says("ready")])
    configured = Mock(spec=ConfiguredChatClientFactory)
    principal = AgentPrincipal(subject="local-user", email="local-user@example.com", roles=frozenset({"mail-user"}))
    factory = MailAgentApplicationFactory(configured)

    runtime = factory.build_composition(
        settings=MailAgentSettings(),
        chat_client=client,
        principal=principal,
        base_path=REPOSITORY_ROOT,
    ).build(session_id="factory-test")
    try:
        assert runtime.agent.client is client
        assert runtime.principal is principal
        assert runtime.user.session_id == "factory-test"
        assert await runtime.mail_tools.list_labels(runtime.user)
        configured.build.assert_not_called()
    finally:
        await runtime.aclose()


def test_factory_reuses_its_configured_chat_client_factory():
    configured = Mock(spec=ConfiguredChatClientFactory)
    client = ScriptedChatClient([says("ready")])
    configured.build.return_value = client
    factory = MailAgentApplicationFactory(configured)

    assert factory.build_chat_client() is client
    assert factory.build_chat_client() is client
    assert configured.build.call_count == 2


@pytest.mark.parametrize(
    ("module", "export"),
    [
        ("adapters.cli.entrypoint", "main"),
        ("adapters.cli.entrypoint", "build_cli"),
        ("adapters.cli.authorise", "main"),
        ("adapters.cli.discover", "main"),
        ("adapters.maf.native", "create_agent"),
        ("bootstrap.service", "build_app"),
    ],
)
def test_canonical_entrypoints_export_callable_factories(module: str, export: str):
    entrypoint = importlib.import_module(f"ai_agent_lab.mail.{module}")
    assert callable(getattr(entrypoint, export))
