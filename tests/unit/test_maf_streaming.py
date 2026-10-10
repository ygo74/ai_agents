from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from agent_framework import AgentResponseUpdate, Content
from agent_framework._types import ContentType
from ygo74.agent_runtime.domains.contracts.agent_output import Notification
from ygo74.agent_runtime.domains.contracts.stream_events import (
    ContentEnd,
    ContentEvent,
    ContentStart,
    TextDelta,
    UsageEvent,
)

from ai_agent_lab.maf.streaming import MafStreamEventTranslator


async def updates() -> AsyncIterator[AgentResponseUpdate]:
    call = Content.from_function_call(
        "call-1", "private_tool", arguments={"secret": "DO_NOT_STREAM"}
    )
    yield AgentResponseUpdate(
        role="assistant",
        contents=[
            call,
            Content.from_text("hello"),
            Content.from_text_reasoning(text="PRIVATE_REASONING"),
        ],
    )
    yield AgentResponseUpdate(role="assistant", contents=[call])
    yield AgentResponseUpdate(
        role="assistant",
        contents=[
            Content.from_function_result("call-1", result={"secret": "DO_NOT_STREAM"}),
            Content.from_text(" world"),
            Content.from_usage(
                {"input_token_count": 4, "output_token_count": 2, "total_token_count": 6}
            ),
        ],
    )


async def test_translates_text_and_safe_tool_activity_without_private_payloads() -> None:
    events = [event async for event in MafStreamEventTranslator().translate(updates(), content_id="content-1")]

    assert isinstance(events[0], ContentEvent)
    assert isinstance(events[0].content, Notification)
    assert events[0].content.text == "Calling private_tool…"
    text_start = next(event for event in events if isinstance(event, ContentStart))
    assert text_start.content_id == "content-1"
    assert [event.text for event in events if isinstance(event, TextDelta)] == ["hello", " world"]
    assert isinstance(events[-1], ContentEnd)
    assert sum(isinstance(event, ContentEvent) for event in events) == 2
    completion = next(
        event for event in events
        if isinstance(event, ContentEvent) and event.content_id.endswith("activity-1")
    )
    assert isinstance(completion.content, Notification)
    assert completion.content.text == "Completed private_tool."
    usage = next(event for event in events if isinstance(event, UsageEvent))
    assert (usage.usage.input_tokens, usage.usage.output_tokens, usage.usage.total_tokens) == (4, 2, 6)
    assert not any(
        secret in repr(event)
        for event in events
        for secret in ("DO_NOT_STREAM", "PRIVATE_REASONING")
    )


@pytest.mark.parametrize("content_type", ContentType.__args__)
async def test_every_maf_content_type_is_translated_or_deliberately_filtered(
    content_type: str,
) -> None:
    content = Content(
        type=content_type,
        text="visible text",
        message="DO_NOT_STREAM_ERROR",
        error_details="DO_NOT_STREAM_DETAILS",
        uri="https://example.test/DO_NOT_STREAM_URI",
        call_id="call-1",
        name="sample_tool",
        tool_name="sample_tool",
        arguments={"secret": "DO_NOT_STREAM_ARGUMENTS"},
        result={"secret": "DO_NOT_STREAM_RESULT"},
        usage_details={"input_token_count": 3, "output_token_count": 2},
    )
    async def one_update() -> AsyncIterator[AgentResponseUpdate]:
        yield AgentResponseUpdate(role="assistant", contents=[content])

    events = [
        event
        async for event in MafStreamEventTranslator().translate(
            one_update(), content_id="content-1"
        )
    ]

    if content_type == "text":
        assert any(isinstance(event, TextDelta) and event.text == "visible text" for event in events)
    elif content_type == "text_reasoning":
        assert events == []
    elif content_type == "usage":
        assert any(isinstance(event, UsageEvent) for event in events)
    else:
        activity = next(event for event in events if isinstance(event, ContentEvent))
        assert isinstance(activity.content, Notification)
    assert not any("DO_NOT_STREAM" in repr(event) for event in events)
