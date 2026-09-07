"""Tests of what the agent offers depending on the bound mail server.

Servers do not cover the same surface. The official Gmail server has no send
tool and no per-message retrieval; a server built on EWS will have its own
gaps. Advertising a capability no server can honour turns into a refusal in the
middle of a conversation, so the registry is filtered by what the backend
declares.

Nothing here opens a connection: only the delivered binding is read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.maf_fakes import ScriptedChatClient, says

from ai_agent_lab.application.mail.composition import MailAgentCompositionRoot
from ai_agent_lab.infrastructure.config.settings import MailAgentSettings
from ai_agent_lab.infrastructure.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.infrastructure.inmemory.reasoner import ScriptedTextReasoner
from ai_agent_lab.mcp.mail.catalog import MailToolName

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

ANALYSIS_TOOLS = frozenset({"summarise_mail", "classify_mail", "extract_mail_actions", "draft_mail_reply"})


def exposed(monkeypatch, *, mode: str, server: str) -> frozenset[str]:
    """Return the tool names the agent would offer for a given backend.

    The mail tools are supplied here, so selecting a server whose dialect is not
    implemented yet still exercises what the agent would advertise.
    """
    monkeypatch.setenv("MAIL_AGENT_MODE", mode)
    monkeypatch.setenv("MAIL_MCP_SERVER", server)
    runtime = MailAgentCompositionRoot(
        MailAgentSettings(),
        ScriptedChatClient([says("nothing to do")]),
        mail_tools=InMemoryMailTools({}),
        reasoner=ScriptedTextReasoner({}),
        base_path=REPOSITORY_ROOT,
    ).build(session_id="exposure")
    return frozenset(descriptor.tool_name for descriptor in runtime.registry.skills)


class TestMockExposesEverything:
    """The deterministic dataset serves the whole contract."""

    def test_every_capability_is_offered(self, monkeypatch):
        names = exposed(monkeypatch, mode="mock", server="local")

        assert {name.value for name in MailToolName} - {"create_draft"} <= names
        assert names >= ANALYSIS_TOOLS


class TestLocalServerExposesEverything:
    """A server implementing the contract natively hides nothing."""

    def test_sending_is_offered(self, monkeypatch):
        names = exposed(monkeypatch, mode="mcp", server="local")

        assert MailToolName.SEND_MAIL.value in names
        assert MailToolName.GET_MAIL.value in names


class TestGmailExposesWhatItCanServe:
    """The official Gmail server has real gaps, and the agent respects them."""

    @pytest.mark.security
    def test_sending_is_not_offered(self, monkeypatch):
        """The official server has no send tool, so the agent never offers one.

        Offering it would let the model propose an irreversible action that no
        backend could carry out.
        """
        names = exposed(monkeypatch, mode="mcp", server="gmail")

        assert MailToolName.SEND_MAIL.value not in names

    def test_per_message_retrieval_is_offered(self, monkeypatch):
        """The live server has get_message, although the published guide omits it."""
        names = exposed(monkeypatch, mode="mcp", server="gmail")

        assert MailToolName.GET_MAIL.value in names

    def test_what_gmail_serves_is_still_offered(self, monkeypatch):
        names = exposed(monkeypatch, mode="mcp", server="gmail")

        assert MailToolName.GET_THREAD.value in names
        assert MailToolName.SEARCH_MAIL.value in names
        assert MailToolName.APPLY_LABEL.value in names
        assert MailToolName.ARCHIVE_MAIL.value in names

    def test_analysis_capabilities_never_depend_on_a_server(self, monkeypatch):
        """Summarising and classifying run on retrieved content, not on a tool."""
        names = exposed(monkeypatch, mode="mcp", server="gmail")

        assert names >= ANALYSIS_TOOLS
