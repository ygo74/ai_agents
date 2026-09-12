"""The Mail Agent as an OpenAI-compatible HTTP service.

Routing, protocol shapes and authentication come from ``ygo74-agent-runtime``.
Microsoft's own guidance for self-hosting says the same about its helpers: they
convert protocol data, and the application owns the route, the identity and the
partitioning of state. That is exactly the split here.

This module is the seam, and it has one rule: it is the **only** place allowed to
see the runtime's loosely-typed payload. Everything it hands onwards is a typed
model - the same discipline ``MailWireMapper`` applies at the MCP boundary. A
transport is weakly typed by nature; the application does not have to be.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ygo74.agent_runtime import (
    AgentCapabilitySet,
    AgentDescriptor,
    AgentSkill,
    Modality,
)

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.core.serving.conversation import AgentReply, ConversationTurn
from ai_agent_lab.mail.application.entrypoints.conversation import MailConversationEngine

CONVERSATION_HEADER = "x-conversation-id"

_INPUT = "input"
_METADATA = "metadata"
_AUTH_CONTEXT = "auth_context"
_HEADERS = "headers"
_ROLE = "role"
_CONTENT = "content"
_USER = "user"
_TEXT = "text"


class EmptyRequestError(DomainError):
    """Raised when a request carries nothing for the agent to answer.

    Reported rather than answered with silence: an agent replying to an empty
    message would look like a model failure instead of a malformed request.
    """

    def __init__(self) -> None:
        super().__init__("the request carried no user message")


class MailAgentEntrypoint:
    """Turns one runtime payload into a turn, and a reply into a payload."""

    def __init__(self, engine: MailConversationEngine, *, default_conversation: str = "default") -> None:
        self._engine = engine
        self._default_conversation = default_conversation

    async def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Answer one request, as ``add_ai_endpoints`` expects."""
        reply = await self._engine.respond(self.to_turn(payload))
        return self.to_payload(payload, reply)

    def to_turn(self, payload: Mapping[str, Any]) -> ConversationTurn:
        """Read a request into the typed model the agent works with.

        The principal comes from ``auth_context``, which the runtime populated
        from a verified token or an API key. It is never taken from the body: a
        caller must not be able to name themselves.
        """
        return ConversationTurn(
            principal=Principal.from_auth_context(_mapping(payload.get(_AUTH_CONTEXT))),
            conversation_id=self._conversation_of(payload),
            message=_latest_message(payload.get(_INPUT)),
        )

    @staticmethod
    def to_payload(payload: Mapping[str, Any], reply: AgentReply) -> dict[str, Any]:
        """Render a reply in the exchange shape the runtime maps to OpenAI."""
        return {
            "request_id": str(payload.get("request_id", "")),
            "status": "success",
            "output": reply.text,
            "metadata": {
                "route_key": str(payload.get("route_key", "")),
                "pending_confirmations": list(reply.pending_confirmations),
            },
        }

    def _conversation_of(self, payload: Mapping[str, Any]) -> str:
        """Find which conversation this request continues.

        LibreChat sends its conversation identifier as a header, because the
        OpenAI schema has no field for one. The runtime forwards it into
        ``metadata``, both under a stable key and among the headers it carried;
        both are read so the agent does not depend on which of the two a given
        runtime version populates.

        A stable default is used when neither is present. Falling back is safe:
        the identifier only selects state *within* an authenticated subject, so
        at worst one caller's turns share a conversation, never two callers.
        """
        metadata = _mapping(payload.get(_METADATA))
        headers = _mapping(metadata.get(_HEADERS))
        for source, key in ((metadata, "conversation_id"), (headers, CONVERSATION_HEADER)):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return self._default_conversation


class MailAgentDescriptorFactory:
    """Describes the agent to discovery, from the configuration it was built with.

    The identity, the description and the capabilities already live in
    ``config/agents/mail/agent.yaml``. Writing them a second time here would let
    the two drift, and what a caller discovers would stop matching what the agent
    actually does.
    """

    def __init__(self, manifest: AgentManifest, *, agent_id: str = "mail-agent") -> None:
        self._manifest = manifest
        self._agent_id = agent_id

    def build(self) -> AgentDescriptor:
        """Build the descriptor the runtime advertises through discovery."""
        return AgentDescriptor(
            agent_id=self._agent_id,
            route_key=self._agent_id,
            display_name=self._manifest.name,
            description=self._manifest.description,
            version="1.0.0",
            owner="ai-agent-lab",
            created_at_utc=datetime(2026, 9, 7, tzinfo=UTC),
            capabilities=AgentCapabilitySet(
                streaming=False,
                input_modalities=(Modality.TEXT,),
                output_modalities=(Modality.TEXT,),
            ),
            tags=("mail",),
            security_schemes=("jwt", "oidc"),
            skills=tuple(
                AgentSkill(
                    skill_id=skill.tool_name,
                    name=skill.tool_name,
                    description=skill.description,
                )
                for skill in self._manifest.skills
            ),
        )


def _mapping(value: object) -> Mapping[str, Any]:
    """Return a mapping, whatever the transport actually sent."""
    return value if isinstance(value, Mapping) else {}


def _latest_message(value: object) -> str:
    """Return what the person just wrote.

    The history is re-sent in full on every request, so only the last user turn
    is new. Everything before it is already in the agent's own session, and
    replaying it would duplicate the conversation.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in reversed(value):
            if not isinstance(item, Mapping) or item.get(_ROLE) != _USER:
                continue
            if text := _content_text(item.get(_CONTENT)):
                return text
    raise EmptyRequestError


def _content_text(content: object) -> str:
    """Flatten a message content, string or content-part list."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [str(part.get(_TEXT, "")).strip() for part in content if isinstance(part, Mapping) and part.get(_TEXT)]
    return "\n".join(part for part in parts if part)
