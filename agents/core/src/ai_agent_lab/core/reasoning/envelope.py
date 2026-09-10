"""Rendering of a reasoning request into a prompt.

This is where a skill hands untrusted material to a model. The delimiting rules
themselves live in :mod:`ai_agent_lab.core.security.fencing`, shared with the
rendering of tool results, so both paths behave identically.
"""

from __future__ import annotations

from ai_agent_lab.core.reasoning.ports import ReasoningRequest
from ai_agent_lab.core.security.fencing import (
    DEFAULT_UNTRUSTED_SOURCE,
    UntrustedFence,
    untrusted_contract,
)


class PromptEnvelopeBuilder:
    """Renders a :class:`ReasoningRequest` into a prompt string.

    Args:
        source: Where the untrusted material came from, in the words the model
            should read - ``"a mailbox"``, ``"a documentation wiki"``. It is
            named in the prompt, so leaving it at the default tells the model
            less than it could about what it is looking at.
        nonce_bytes: Width of the per-rendering fence delimiter.
    """

    def __init__(self, *, source: str = DEFAULT_UNTRUSTED_SOURCE, nonce_bytes: int = 8) -> None:
        self._source = source
        self._nonce_bytes = nonce_bytes

    def build(self, request: ReasoningRequest) -> str:
        """Render the request, fencing every untrusted section."""
        parts = [request.instructions.strip(), "# Task", request.task.strip()]

        if not request.context:
            return "\n\n".join(parts)

        fence = UntrustedFence(nonce_bytes=self._nonce_bytes)
        parts.append(f"# Untrusted content from {self._source}")
        parts.append(untrusted_contract(self._source))
        parts.extend(fence.render(section.label, section.content.expose()) for section in request.context)
        return "\n\n".join(parts)
