"""Translate framework response updates into provider-neutral stream events."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Mapping

from agent_framework import AgentResponseUpdate, Content
from ygo74.agent_runtime.domains.contracts.agent_output import (
    Notification,
    TextContent,
    TokenUsage,
)
from ygo74.agent_runtime.domains.contracts.stream_events import (
    AgentStreamEvent,
    ContentEnd,
    ContentEvent,
    ContentStart,
    TextDelta,
    UsageEvent,
)

_TOOL_CALL_TYPES = {
    "function_call",
    "code_interpreter_tool_call",
    "image_generation_tool_call",
    "mcp_server_tool_call",
    "search_tool_call",
    "shell_tool_call",
}
_TOOL_RESULT_TYPES = {
    "function_result",
    "code_interpreter_tool_result",
    "image_generation_tool_result",
    "mcp_server_tool_result",
    "search_tool_result",
    "shell_tool_result",
    "shell_command_output",
}
_ACTIVITY_TEXT = {
    "data": "Processing structured content",
    "uri": "Processing referenced content",
    "error": "The agent reported an error",
    "hosted_file": "Accessing a file",
    "hosted_vector_store": "Searching stored documents",
    "function_approval_request": "Waiting for confirmation",
    "function_approval_response": "Confirmation received",
    "oauth_consent_request": "Additional authorization is required",
}


class MafStreamEventTranslator:
    """Translate MAF updates to safe, protocol-neutral stream events."""

    async def translate(
        self,
        updates: AsyncIterable[AgentResponseUpdate],
        *,
        content_id: str,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Translate text, usage, and safe activity indicators from MAF updates."""
        text_started = False
        activity_ids: set[tuple[str, str]] = set()
        tool_names: dict[str, str] = {}
        activity_index = 0

        async for update in updates:
            for content in update.contents or ():
                events, text_started, activity_index = self._content_events(
                    content,
                    content_id=content_id,
                    text_started=text_started,
                    activity_index=activity_index,
                    activity_ids=activity_ids,
                    tool_names=tool_names,
                )
                for event in events:
                    yield event

        if text_started:
            yield ContentEnd(content_id)

    def _content_events(
        self,
        content: Content,
        *,
        content_id: str,
        text_started: bool,
        activity_index: int,
        activity_ids: set[tuple[str, str]],
        tool_names: dict[str, str],
    ) -> tuple[tuple[AgentStreamEvent, ...], bool, int]:
        if content.type == "text":
            return self._text_events(content, content_id, text_started, activity_index)
        if content.type == "usage":
            usage = self._usage_event(content.usage_details)
            return ((usage,) if usage is not None else ()), text_started, activity_index
        if content.type == "text_reasoning":
            return (), text_started, activity_index
        return self._activity_event(
            content,
            content_id=content_id,
            activity_index=activity_index,
            activity_ids=activity_ids,
            tool_names=tool_names,
            text_started=text_started,
        )

    @staticmethod
    def _text_events(
        content: Content,
        content_id: str,
        text_started: bool,
        activity_index: int,
    ) -> tuple[tuple[AgentStreamEvent, ...], bool, int]:
        if not isinstance(content.text, str) or not content.text:
            return (), text_started, activity_index
        events: list[AgentStreamEvent] = []
        if not text_started:
            events.append(ContentStart(content_id, TextContent("")))
        events.append(TextDelta(content_id, content.text))
        return tuple(events), True, activity_index

    def _activity_event(
        self,
        content: Content,
        *,
        content_id: str,
        activity_index: int,
        activity_ids: set[tuple[str, str]],
        tool_names: dict[str, str],
        text_started: bool,
    ) -> tuple[tuple[AgentStreamEvent, ...], bool, int]:
        tool_name = self._safe_tool_name(content.tool_name or content.name)
        if content.type in _TOOL_CALL_TYPES and content.call_id and tool_name:
            tool_names[content.call_id] = tool_name
        notification = self._activity_notification(
            content,
            tool_names.get(content.call_id or ""),
        )
        if notification is None:
            return (), text_started, activity_index
        identity = self._activity_identity(content)
        if identity in activity_ids:
            return (), text_started, activity_index
        activity_ids.add(identity)
        event = ContentEvent(f"{content_id}-activity-{activity_index}", notification)
        return (event,), text_started, activity_index + 1

    @staticmethod
    def _activity_notification(
        content: Content, correlated_tool_name: str | None
    ) -> Notification | None:
        if content.type in _TOOL_CALL_TYPES:
            name = MafStreamEventTranslator._safe_tool_name(
                content.tool_name or content.name
            )
            action = f"Calling {name}" if name else "Calling a tool"
            return Notification(f"{action}…")
        if content.type in _TOOL_RESULT_TYPES:
            name = MafStreamEventTranslator._safe_tool_name(
                content.tool_name or content.name or correlated_tool_name
            )
            action = f"Completed {name}" if name else "Tool execution completed"
            return Notification(f"{action}.")
        message = _ACTIVITY_TEXT.get(content.type)
        return Notification(message) if message is not None else None

    @staticmethod
    def _safe_tool_name(name: str | None) -> str | None:
        if name is None:
            return None
        safe_name = "".join(
            character for character in name[:80] if character.isalnum() or character in "_.:-"
        )
        return safe_name or None

    @staticmethod
    def _activity_identity(content: Content) -> tuple[str, str]:
        identifier = content.call_id or content.id or content.tool_name or content.name
        return content.type, identifier or content.type

    @staticmethod
    def _usage_event(details: object) -> UsageEvent | None:
        if not isinstance(details, Mapping):
            return None
        input_tokens = MafStreamEventTranslator._token_count(details, "input_token_count")
        output_tokens = MafStreamEventTranslator._token_count(details, "output_token_count")
        total_tokens = MafStreamEventTranslator._token_count(details, "total_token_count")
        cached_input_tokens = MafStreamEventTranslator._token_count(
            details, "cache_read_input_token_count"
        )
        reasoning_output_tokens = MafStreamEventTranslator._token_count(
            details, "reasoning_output_token_count"
        )
        cache_write_input_tokens = MafStreamEventTranslator._token_count(
            details, "cache_creation_input_token_count"
        )
        if input_tokens is None and output_tokens is None:
            return None
        input_count = input_tokens or 0
        output_count = output_tokens or 0
        usage = TokenUsage(
            input_tokens=input_count,
            output_tokens=output_count,
            total_tokens=total_tokens if total_tokens is not None else input_count + output_count,
            cached_input_tokens=cached_input_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
        )
        return UsageEvent(usage)

    @staticmethod
    def _token_count(details: Mapping[str, object], key: str) -> int | None:
        value = details.get(key)
        return value if type(value) is int and value >= 0 else None

    @staticmethod
    def complete_text(text: str, *, content_id: str) -> ContentEvent:
        """Represent a complete user-visible text item without protocol details."""
        return ContentEvent(content_id, TextContent(text))
