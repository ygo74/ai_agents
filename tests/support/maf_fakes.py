"""Test doubles for Microsoft Agent Framework.

Agent scenarios must be reproducible, so they run against a scripted chat
client instead of a real model. The agent, the tools, the approval middleware
and every skill are the real ones: only the model is replaced.

The double derives from ``BaseChatClient`` on purpose. The tool-invocation loop
and the approval handling live in that base class, so a duck-typed client would
silently never execute a tool and the scenarios would prove nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_framework import BaseChatClient, ChatResponse, Content, Message
from agent_framework._tools import FunctionInvocationLayer


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation the scripted model asks for."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScriptedTurn:
    """What the scripted model produces for one exchange."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


def calls(*tool_calls: ToolCall) -> ScriptedTurn:
    """Build a turn that only invokes tools."""
    return ScriptedTurn(tool_calls=tool_calls)


def says(text: str) -> ScriptedTurn:
    """Build a turn that only answers."""
    return ScriptedTurn(text=text)


class ScriptedChatClient(FunctionInvocationLayer[Any], BaseChatClient[Any]):
    """Replays a fixed sequence of model turns.

    The tool-invocation loop and the approval handling live in
    ``FunctionInvocationLayer``, which real clients compose. The double composes
    it too, otherwise a scenario would never execute a tool and would prove
    nothing.
    """

    def __init__(self, script: Sequence[ScriptedTurn]) -> None:
        super().__init__()
        self.script = list(script)
        self.turn = 0
        self.offered_tools: list[tuple[str, ...]] = []
        self.received_messages: list[list[Message]] = []

    def append(self, *turns: ScriptedTurn) -> None:
        """Arm additional turns, for scenarios that span several user requests."""
        self.script.extend(turns)

    async def _inner_get_response(  # type: ignore[override]
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> ChatResponse[Any]:
        """Return the next scripted turn as a chat response."""
        self.received_messages.append(list(messages))
        self._record_tools(options)
        self._reject_structured_output(options)
        turn = self._next_turn()
        return ChatResponse(messages=Message(role="assistant", contents=self._contents_of(turn)))

    @staticmethod
    def _contents_of(turn: ScriptedTurn) -> list[Content]:
        """Build the contents of one scripted assistant message."""
        contents: list[Content] = [
            Content.from_function_call(f"call-{uuid.uuid4().hex[:8]}", call.name, arguments=dict(call.arguments))
            for call in turn.tool_calls
        ]
        if turn.text:
            contents.append(Content.from_text(turn.text))
        return contents

    @staticmethod
    def _reject_structured_output(options: Mapping[str, Any]) -> None:
        """Refuse to guess a structured answer.

        Reasoning belongs to the skills, which scenarios drive with a scripted
        reasoner. Silently inventing one here would hide a wiring mistake.
        """
        response_format = options.get("response_format")
        if response_format is not None:
            raise AssertionError(
                f"the scripted chat client was asked for a {response_format.__name__}; "
                "inject a ScriptedTextReasoner instead"
            )

    def _record_tools(self, options: Mapping[str, Any]) -> None:
        """Capture the tools offered to the model."""
        tools = options.get("tools") or []
        self.offered_tools.append(tuple(getattr(tool, "name", "") for tool in tools))

    def _next_turn(self) -> ScriptedTurn:
        """Return the next scripted turn, or a default closing answer."""
        if self.turn >= len(self.script):
            return says("(the scripted model has nothing left to say)")
        turn = self.script[self.turn]
        self.turn += 1
        return turn
