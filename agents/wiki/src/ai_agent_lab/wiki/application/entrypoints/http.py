"""The Wiki Agent as an OpenAI-compatible HTTP service.

Routing, protocol shapes and authentication come from ``ygo74-agent-runtime``.
What the application owns is which caller a request is attributed to, which
conversation it continues, and what is done with a gated operation - the same
split the Mail Agent applies, so the two are served identically and a comparison
between the frameworks measures the frameworks.

Reading the runtime's loosely-typed payload is not specific to a wiki, so it
lives in :mod:`ygo74.agent_runtime.domains.endpoints.conversation_payloads` and this module composes it.

**One thing is specific, and it is stated here.** A wiki account is not an e-mail
address. Confluence identifies a person by an account identifier, Data Center by
a username, and an identity provider may assert neither an address nor a verified
one. Demanding an e-mail would refuse callers this agent can serve perfectly
well, and inventing one would be worse, so the reader is built without that
requirement. The subject is still mandatory: it is what every ticket, ledger
entry and audit record is partitioned by.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ygo74.agent_runtime import AgentDescriptor
from ygo74.agent_runtime.domains.contracts.contract_errors import EmptyRequestError
from ygo74.agent_runtime.domains.contracts.conversation import AgentReply, ConversationTurn
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import (
    AdvertisedSecurity,
    AgentDescriptorFactory,
)
from ygo74.agent_runtime.domains.endpoints.conversation_payloads import (
    DEFAULT_CONVERSATION,
    AgentReplyRenderer,
    ConversationPayloadReader,
)
from ygo74.agent_runtime.domains.endpoints.header_forwarding import DEFAULT_CONVERSATION_HEADER

from ai_agent_lab.wiki.application.entrypoints.conversation import WikiConversationEngine

__all__ = [
    "DEFAULT_CONVERSATION_HEADER",
    "EmptyRequestError",
    "WikiAgentDescriptorFactory",
    "WikiAgentEntrypoint",
]

PUBLISHED_AT = datetime(2026, 9, 12, tzinfo=UTC)

# Who operates the agent. Stated rather than defaulted: the library's own default
# names the library, which would publish the wrong owner for every agent here.
OWNER = "ai-agent-lab"


class WikiAgentEntrypoint:
    """Turns one runtime payload into a turn, and a reply into a payload."""

    def __init__(
        self,
        engine: WikiConversationEngine,
        *,
        default_conversation: str = DEFAULT_CONVERSATION,
    ) -> None:
        self._engine = engine
        # A wiki account is not an e-mail address: see the module docstring.
        self._reader = ConversationPayloadReader(
            require_email=False,
            default_conversation=default_conversation,
        )
        self._renderer = AgentReplyRenderer()

    async def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Answer one request, as ``add_ai_endpoints`` expects."""
        reply = await self._engine.respond(self.to_turn(payload))
        return self.to_payload(payload, reply)

    def to_turn(self, payload: Mapping[str, Any]) -> ConversationTurn:
        """Read a request into the typed model the agent works with.

        The principal comes from ``auth_context``, which the runtime populated
        from a verified token or an API key. It is never taken from the body: a
        caller must not be able to name themselves, least of all on a wiki where
        naming somebody else would hand over their restricted spaces.
        """
        return self._reader.to_turn(payload)

    def to_payload(self, payload: Mapping[str, Any], reply: AgentReply) -> dict[str, Any]:
        """Render a reply in the exchange shape the runtime maps to OpenAI."""
        return self._renderer.to_payload(payload, reply)


class WikiAgentDescriptorFactory:
    """Describes the Wiki Agent to discovery, from its delivered manifest.

    The authentication is passed in rather than assumed: the Wiki Agent runs
    behind a realm or behind a single demonstration key, and a caller reading the
    descriptor has to be told which.
    """

    def __init__(
        self,
        manifest: AgentManifest,
        *,
        security: AdvertisedSecurity,
        agent_id: str = "wiki-agent",
    ) -> None:
        self._factory = AgentDescriptorFactory(
            manifest,
            agent_id=agent_id,
            tags=("wiki",),
            created_at=PUBLISHED_AT,
            owner=OWNER,
            security=security,
        )

    def build(self) -> AgentDescriptor:
        """Build the descriptor the runtime advertises through discovery."""
        return self._factory.build()
