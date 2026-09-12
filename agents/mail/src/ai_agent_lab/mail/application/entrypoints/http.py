"""The Mail Agent as an OpenAI-compatible HTTP service.

Routing, protocol shapes and authentication come from ``ygo74-agent-runtime``.
Microsoft's own guidance for self-hosting says the same about its helpers: they
convert protocol data, and the application owns the route, the identity and the
partitioning of state. That is exactly the split here.

Reading the runtime's loosely-typed payload is not specific to mail, so it lives
in :mod:`ai_agent_lab.core.serving.payloads` and this module composes it. What
*is* specific is stated here and nowhere else: a caller of this agent must carry
an e-mail address, because a mailbox is addressed by one and defaulting it would
pick a victim.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ygo74.agent_runtime import AgentDescriptor

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.serving.conversation import AgentReply, ConversationTurn
from ai_agent_lab.core.serving.discovery import AgentDescriptorFactory
from ai_agent_lab.core.serving.payloads import (
    CONVERSATION_HEADER,
    DEFAULT_CONVERSATION,
    AgentReplyRenderer,
    ConversationPayloadReader,
    EmptyRequestError,
)
from ai_agent_lab.mail.application.entrypoints.conversation import MailConversationEngine

__all__ = [
    "CONVERSATION_HEADER",
    "EmptyRequestError",
    "MailAgentDescriptorFactory",
    "MailAgentEntrypoint",
]

PUBLISHED_AT = datetime(2026, 9, 7, tzinfo=UTC)
_logger = logging.getLogger(__name__)


class MailAgentEntrypoint:
    """Turns one runtime payload into a turn, and a reply into a payload."""

    def __init__(
        self,
        engine: MailConversationEngine,
        *,
        default_conversation: str = DEFAULT_CONVERSATION,
    ) -> None:
        _logger.info("Initializing Mail Agent HTTP entry point")
        _logger.debug(
            "MailAgentEntrypoint.__init__ arguments: engine_type=%s, default_conversation=%s",
            type(engine).__name__,
            default_conversation,
        )
        self._engine = engine
        # A mailbox is addressed by e-mail, so a caller without one is refused
        # rather than served somebody else's mail.
        self._reader = ConversationPayloadReader(
            require_email=True,
            default_conversation=default_conversation,
        )
        self._renderer = AgentReplyRenderer()

    async def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Answer one request, as ``add_ai_endpoints`` expects."""
        _logger.info("Handling Mail Agent HTTP request")
        _logger.debug(
            "MailAgentEntrypoint.__call__ arguments: payload_keys=%s",
            tuple(sorted(str(key) for key in payload)),
        )
        reply = await self._engine.respond(self.to_turn(payload))
        return self.to_payload(payload, reply)

    def to_turn(self, payload: Mapping[str, Any]) -> ConversationTurn:
        """Read a request into the typed model the agent works with."""
        _logger.info("Reading Mail Agent HTTP conversation turn")
        _logger.debug(
            "MailAgentEntrypoint.to_turn arguments: payload_keys=%s",
            tuple(sorted(str(key) for key in payload)),
        )
        return self._reader.to_turn(payload)

    def to_payload(self, payload: Mapping[str, Any], reply: AgentReply) -> dict[str, Any]:
        """Render a reply in the exchange shape the runtime maps to OpenAI."""
        _logger.info("Rendering Mail Agent HTTP response payload")
        _logger.debug(
            "MailAgentEntrypoint.to_payload arguments: payload_keys=%s, reply_length=%d, pending_confirmations=%d",
            tuple(sorted(str(key) for key in payload)),
            len(reply.text),
            len(reply.pending_confirmations),
        )
        return self._renderer.to_payload(payload, reply)


class MailAgentDescriptorFactory:
    """Describes the Mail Agent to discovery, from its delivered manifest."""

    def __init__(self, manifest: AgentManifest, *, agent_id: str = "mail-agent") -> None:
        _logger.info("Initializing Mail Agent descriptor factory")
        _logger.debug(
            "MailAgentDescriptorFactory.__init__ arguments: agent_name=%s, agent_id=%s, skill_count=%d",
            manifest.name,
            agent_id,
            len(manifest.skills),
        )
        self._factory = AgentDescriptorFactory(
            manifest,
            agent_id=agent_id,
            tags=("mail",),
            created_at=PUBLISHED_AT,
        )

    def build(self) -> AgentDescriptor:
        """Build the descriptor the runtime advertises through discovery."""
        _logger.info("Building Mail Agent discovery descriptor")
        _logger.debug("MailAgentDescriptorFactory.build arguments: none")
        return self._factory.build()
