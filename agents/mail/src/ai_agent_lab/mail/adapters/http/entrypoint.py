"""The Mail Agent as an OpenAI-compatible HTTP service.

Routing, protocol shapes and authentication come from ``ygo74-agent-runtime``.
Microsoft's own guidance for self-hosting says the same about its helpers: they
convert protocol data, and the application owns the route, the identity and the
partitioning of state. That is exactly the split here.

Reading the runtime's loosely-typed payload is not specific to mail, so it lives
in :mod:`ygo74.agent_runtime.domains.endpoints.conversation_payloads` and this module composes it. What
*is* specific is stated here and nowhere else: a caller of this agent must carry
an e-mail address, because a mailbox is addressed by one and defaulting it would
pick a victim.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ygo74.agent_runtime.domains.contracts.contract_errors import EmptyRequestError
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.discovery.agent_descriptor import AgentDescriptor
from ygo74.agent_runtime.domains.discovery.manifest_descriptor import (
    AdvertisedSecurity,
    AgentDescriptorFactory,
)
from ygo74.agent_runtime.domains.endpoints.conversation_entrypoint import ConversationEntrypoint
from ygo74.agent_runtime.domains.endpoints.conversation_payloads import DEFAULT_CONVERSATION
from ygo74.agent_runtime.domains.endpoints.header_forwarding import DEFAULT_CONVERSATION_HEADER

from ai_agent_lab.mail.bootstrap.conversation import MailConversationEngine

__all__ = [
    "DEFAULT_CONVERSATION_HEADER",
    "EmptyRequestError",
    "MailAgentDescriptorFactory",
    "MailAgentEntrypoint",
]

PUBLISHED_AT = datetime(2026, 9, 7, tzinfo=UTC)

# Who operates the agent. Stated rather than defaulted: the library's own default
# names the library, which would publish the wrong owner for every agent here.
OWNER = "ai-agent-lab"

_logger = logging.getLogger(__name__)


class MailAgentEntrypoint(ConversationEntrypoint):
    """Declare Mail's email requirement on the shared transport binding."""

    def __init__(
        self,
        engine: MailConversationEngine,
        *,
        default_conversation: str = DEFAULT_CONVERSATION,
    ) -> None:
        super().__init__(engine, require_email=True, default_conversation=default_conversation)


class MailAgentDescriptorFactory:
    """Describes the Mail Agent to discovery, from its delivered manifest.

    The authentication is passed in rather than assumed. The Mail Agent runs
    behind a realm in a real deployment and behind a single API key in a
    demonstration, and discovery has to say which - advertising a bearer scheme a
    service does not accept sends a caller to a door that is not there.
    """

    def __init__(
        self,
        manifest: AgentManifest,
        *,
        security: AdvertisedSecurity,
        agent_id: str = "mail-agent",
    ) -> None:
        _logger.info("Initializing Mail Agent descriptor factory")
        _logger.debug(
            "MailAgentDescriptorFactory.__init__ arguments: agent_name=%s, agent_id=%s, skill_count=%d, schemes=%s",
            manifest.name,
            agent_id,
            len(manifest.skills),
            security.names(),
        )
        self._factory = AgentDescriptorFactory(
            manifest,
            agent_id=agent_id,
            tags=("mail",),
            created_at=PUBLISHED_AT,
            owner=OWNER,
            security=security,
        )

    def build(self) -> AgentDescriptor:
        """Build the descriptor the runtime advertises through discovery."""
        _logger.info("Building Mail Agent discovery descriptor")
        _logger.debug("MailAgentDescriptorFactory.build arguments: none")
        return self._factory.build()
