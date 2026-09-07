"""Conformance of the real MCP client, over a real protocol stack.

The suite these tests reuse was written against the contract, not against the
in-memory double. Running it here proves the point it was written for: the
client, the transport and a server implementing the payload contract behave
exactly like the mock the rest of the suite uses.

No network, no credentials and no mailbox: the server under test is the
reference server, started as a subprocess over stdio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.contract.test_mail_tools_contract import MailToolsContractTests

from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.domain.models import MailSearchRequest
from ai_agent_lab.mail.mail_errors import MailAccessDeniedError, MailNotFoundError
from ai_agent_lab.mail.mcp.binding import McpServerBinding, McpTransport
from ai_agent_lab.mail.mcp.connection import McpConnection
from ai_agent_lab.mail.mcp.native.client import McpMailTools

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPOSITORY_ROOT / "tests" / "contract" / "mcp_contract_mailbox.json"

OWNER_ID = "owner"


def binding() -> McpServerBinding:
    """Describe the reference server as a stdio deployment."""
    return McpServerBinding(
        server="reference",
        transport=McpTransport.STDIO,
        capabilities=tuple(MailToolName),
        tools={name.value: name.value for name in MailToolName},
        command="python",
        args=("-m", "mail_mcp.reference.server", "--dataset", str(DATASET)),
    )


@pytest.fixture
async def connected_tools():
    """Start the reference server and connect the real client to it."""
    connection = McpConnection(binding())
    tools = McpMailTools(connection, binding(), owner_id=OWNER_ID)
    try:
        yield tools
    finally:
        await connection.aclose()


class TestMcpMailToolsContract(MailToolsContractTests):
    """The MCP client honours the mail contract, exactly like the mock."""

    @pytest.fixture
    def mail_tools(self, connected_tools):
        """Return the client under test."""
        return connected_tools


class TestErrorsCrossTheBoundary:
    """A failure must keep its meaning after crossing the protocol."""

    async def test_a_missing_message_is_still_a_missing_message(self, connected_tools, owner):
        with pytest.raises(MailNotFoundError):
            await connected_tools.get_message("does-not-exist", owner)

    @pytest.mark.security
    async def test_another_mailbox_is_refused_before_the_call(self, connected_tools, reader):
        """The client does not even ask for a mailbox it does not serve."""
        with pytest.raises(MailAccessDeniedError):
            await connected_tools.search(MailSearchRequest(unread_only=True), reader)


class TestUntrustedContentIsFenced:
    """Everything the server returns is third-party content."""

    async def test_a_subject_arrives_fenced(self, connected_tools, owner):
        message = await connected_tools.get_message("m1", owner)

        assert message.subject.expose() == "Project Alpha review"
        assert "Project Alpha" not in repr(message.subject)

    async def test_a_body_arrives_fenced(self, connected_tools, owner):
        message = await connected_tools.get_message("m1", owner)

        assert "review" in message.body.expose()
        assert "review" not in repr(message.body)

    async def test_timestamps_survive_the_round_trip(self, connected_tools, owner):
        message = await connected_tools.get_message("m1", owner)

        assert message.sent_at == datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
