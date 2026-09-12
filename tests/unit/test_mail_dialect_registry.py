"""What it takes to plug a mail server that never heard of us.

This is the normal case, not the exception. The official Google server, a server
for Yahoo, one for Fastmail: none of them implements our protocol, and none of
them ever will. The claim this file makes executable is that reaching one costs
a dialect class and a binding file, and changes nothing in the domain, the
skills or the agent.

The fictional "Bluebird" server here is deliberately unlike ours: it has its own
tool names, and no send tool at all.
"""

from __future__ import annotations

import pytest
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.domain.models import (
    MailDraft,
    MailLabel,
    MailLabelOutcome,
    MailMessage,
    MailSearchRequest,
    MailSearchResult,
    MailSendRequest,
    MailSendResult,
    MailThread,
)
from ai_agent_lab.mail.mail_errors import MailToolUnavailableError
from ai_agent_lab.mail.mcp.binding import McpServerBinding, McpTransport
from ai_agent_lab.mail.mcp.connection import McpConnection
from ai_agent_lab.mail.mcp.dialects import GMAIL, NATIVE, MailDialectRegistry
from ai_agent_lab.mail.tools_port import MailTools

BLUEBIRD = "bluebird"


class BluebirdMailTools:
    """A dialect for a server with its own names and its own gaps.

    It implements :class:`MailTools` and nothing else. Note what it does not
    import: no protocol package, no payload module. A third-party server is
    reached through translation, never through compliance.

    The bodies are left unimplemented on purpose: what is under test is that a
    dialect plugs in, not that this fictional server works.
    """

    def __init__(self, connection: McpConnection, binding: McpServerBinding, *, owner_id: str) -> None:
        self.connection = connection
        self.binding = binding
        self.owner_id = owner_id

    async def search(self, request: MailSearchRequest, user: UserContext) -> MailSearchResult:
        raise NotImplementedError

    async def get_message(self, message_id: str, user: UserContext) -> MailMessage:
        raise NotImplementedError

    async def get_thread(self, thread_id: str, user: UserContext) -> MailThread:
        raise NotImplementedError

    async def list_labels(self, user: UserContext) -> tuple[MailLabel, ...]:
        raise NotImplementedError

    async def create_draft(self, draft: MailDraft, user: UserContext) -> MailDraft:
        raise NotImplementedError

    async def send(self, request: MailSendRequest, user: UserContext) -> MailSendResult:
        raise NotImplementedError

    async def set_read_state(self, message_id: str, is_read: bool, user: UserContext) -> None:
        raise NotImplementedError

    async def archive(self, message_id: str, user: UserContext) -> None:
        raise NotImplementedError

    async def apply_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        raise NotImplementedError

    async def remove_label(self, message_id: str, label_id: str, user: UserContext) -> None:
        raise NotImplementedError

    async def create_label(self, name: str, user: UserContext) -> MailLabelOutcome:
        raise NotImplementedError

    async def delete_label(self, label_id: str, user: UserContext) -> None:
        raise NotImplementedError


def _bluebird(connection: McpConnection, binding: McpServerBinding, owner_id: str) -> MailTools:
    """Build the client of the Bluebird server."""
    return BluebirdMailTools(connection, binding, owner_id=owner_id)


# A binding as it would be delivered in `config/mcp/bluebird.yaml`.
BLUEBIRD_BINDING = McpServerBinding(
    server=BLUEBIRD,
    transport=McpTransport.STDIO,
    # No send tool: this server can read and organise, and that is all.
    capabilities=(
        MailToolName.SEARCH_MAIL,
        MailToolName.GET_MAIL,
        MailToolName.GET_THREAD,
        MailToolName.LIST_LABELS,
        MailToolName.MARK_READ,
    ),
    # Its own names, which is exactly why a dialect is needed.
    tools={
        MailToolName.SEARCH_MAIL.value: "bluebird.findMail",
        MailToolName.GET_MAIL.value: "bluebird.readMail",
        MailToolName.GET_THREAD.value: "bluebird.readConversation",
        MailToolName.LIST_LABELS.value: "bluebird.folders",
        MailToolName.MARK_READ.value: "bluebird.setSeen",
    },
    dialect=BLUEBIRD,
    command="python",
    args=("-m", "bluebird.server"),
)


class TestAThirdPartyServerPlugsIn:
    """Registering a dialect is the whole cost of a new server."""

    def test_a_registered_dialect_is_built_from_its_binding(self):
        registry = MailDialectRegistry()
        registry.register(BLUEBIRD, _bluebird)

        built = registry.build(_connection(), BLUEBIRD_BINDING, "local-user")

        assert isinstance(built, BluebirdMailTools)
        assert built.owner_id == "local-user"

    def test_the_dialect_satisfies_the_port_the_skills_depend_on(self):
        """The skills depend on ``MailTools``, so this is what "plugs in" means."""
        built = BluebirdMailTools(_connection(), BLUEBIRD_BINDING, owner_id="local-user")

        assert isinstance(built, MailTools)

    def test_a_server_may_declare_fewer_capabilities_than_the_catalogue(self):
        """A gap is declared in the binding, not discovered on the first call."""
        assert MailToolName.SEND_MAIL not in BLUEBIRD_BINDING.capabilities
        assert MailToolName.SEARCH_MAIL in BLUEBIRD_BINDING.capabilities

    def test_the_binding_carries_the_names_the_server_actually_uses(self):
        assert BLUEBIRD_BINDING.remote(MailToolName.SEARCH_MAIL.value) == "bluebird.findMail"


class TestTheRegistryIsExplicit:
    """Which servers a build can reach is readable in one place."""

    def test_the_built_in_dialects_are_still_there(self):
        assert MailDialectRegistry().known == (GMAIL, NATIVE)

    def test_registering_a_dialect_never_silently_replaces_one(self):
        """A typo must not shadow the dialect a deployment relies on."""
        registry = MailDialectRegistry()

        with pytest.raises(MailToolUnavailableError):
            registry.register(NATIVE, _bluebird)

    def test_an_unknown_dialect_names_the_alternatives(self):
        """A misspelled binding should say what it could have said instead."""
        registry = MailDialectRegistry()

        with pytest.raises(MailToolUnavailableError) as failure:
            registry.build(_connection(), BLUEBIRD_BINDING, "local-user")

        message = str(failure.value)
        assert BLUEBIRD in message
        assert NATIVE in message
        assert GMAIL in message


def _connection() -> McpConnection:
    """A connection object that is never opened."""
    return McpConnection(BLUEBIRD_BINDING, timeout_seconds=1)
