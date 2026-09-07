"""Rendering of a reasoning request into a prompt.

This is where a skill hands untrusted material to a model. The delimiting rules
themselves live in :mod:`ai_agent_lab.core.security.fencing`, shared with the
rendering of tool results, so both paths behave identically.
"""

from __future__ import annotations

from ai_agent_lab.core.reasoning.ports import ReasoningRequest
from ai_agent_lab.core.security.fencing import UNTRUSTED_CONTRACT, UntrustedFence


class PromptEnvelopeBuilder:
    """Renders a :class:`ReasoningRequest` into a prompt string."""

    def __init__(self, *, nonce_bytes: int = 8) -> None:
        self._nonce_bytes = nonce_bytes

    def build(self, request: ReasoningRequest) -> str:
        """Render the request, fencing every untrusted section."""
        parts = [request.instructions.strip(), "# Task", request.task.strip()]

        if not request.context:
            return "\n\n".join(parts)

        fence = UntrustedFence(nonce_bytes=self._nonce_bytes)
        parts.append("# Untrusted mailbox content")
        parts.append(UNTRUSTED_CONTRACT)
        parts.extend(fence.render(section.label, section.content.expose()) for section in request.context)
        return "\n\n".join(parts)
