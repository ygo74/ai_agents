"""Test doubles for LangChain / LangGraph.

Agent scenarios must be reproducible, so they run against a scripted chat model
instead of a real one. The agent, the tools, the human-in-the-loop middleware and
every skill are the real ones: only the model is replaced.

The double derives from ``BaseChatModel`` on purpose. LangGraph's agent loop
inspects the messages a model returns and executes ``tool_calls`` itself, so a
duck-typed object would either be rejected outright or silently never trigger a
tool, and the scenarios would prove nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


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


class ScriptedChatModel(BaseChatModel):
    """Replays a fixed sequence of model turns.

    Once the script is exhausted the model answers with an empty message rather
    than raising. A turn that ran one more round than expected is then a readable
    assertion failure about the conversation, not a stack trace from inside the
    framework.
    """

    script: list[ScriptedTurn] = Field(default_factory=list)
    prompts: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[str] = Field(default_factory=list)

    def __init__(self, script: Sequence[ScriptedTurn], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.script = list(script)
        self.prompts = []
        self.bound_tools = []

    @property
    def _llm_type(self) -> str:
        """Identify the double in traces."""
        return "scripted"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Accept the tools the agent binds, and record their names.

        The base class raises ``NotImplementedError`` here, which is how a real
        model without tool support announces itself. The agent binds tools before
        every model call, so a double that did not accept them would fail before
        a single tool ever ran.

        The double returns *itself* rather than a bound wrapper: the script
        already decides which tools are called, and going through a wrapper would
        only add a layer between the test and what it is asserting.
        """
        del tool_choice, kwargs
        self.bound_tools = [getattr(tool, "name", str(tool)) for tool in tools]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Return the next scripted turn as an assistant message."""
        del stop, run_manager, kwargs
        self.prompts.append(list(messages))
        turn = self.script.pop(0) if self.script else ScriptedTurn()
        return ChatResult(generations=[ChatGeneration(message=self._message(turn))])

    @staticmethod
    def _message(turn: ScriptedTurn) -> AIMessage:
        """Build the assistant message of one scripted turn."""
        return AIMessage(
            content=turn.text,
            tool_calls=[
                {
                    "name": call.name,
                    "args": dict(call.arguments),
                    "id": f"call-{uuid4().hex[:8]}",
                    "type": "tool_call",
                }
                for call in turn.tool_calls
            ],
        )


class ScriptedStructuredModel(BaseChatModel):
    """Answers ``with_structured_output`` with a prepared object.

    The reasoning port asks for a typed answer, and the real path goes through
    ``with_structured_output``. Overriding that method is what makes the double
    exercise the reasoner rather than replace it.
    """

    answer: Any = None

    def __init__(self, answer: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.answer = answer

    @property
    def _llm_type(self) -> str:
        """Identify the double in traces."""
        return "scripted-structured"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Never reached: structured output is intercepted below."""
        del messages, stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Return a runnable handing back the prepared answer."""
        del schema, kwargs
        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(lambda _: self.answer)
