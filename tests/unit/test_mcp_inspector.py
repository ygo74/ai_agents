"""Tests for the developer command that inspects hosted agent MCP tools."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from scripts import inspect_mcp


def test_headers_are_loaded_from_environment_without_changing_their_values() -> None:
    """Resolve configured header values from environment variables."""
    headers = inspect_mcp.headers_from_environment(
        ["Authorization=MAIL_AUTH_HEADER", "X-API-Key=WIKI_API_KEY"],
        {"MAIL_AUTH_HEADER": "Bearer test-token", "WIKI_API_KEY": "wiki-secret"},
    )

    assert headers == {"Authorization": "Bearer test-token", "X-API-Key": "wiki-secret"}


@pytest.mark.parametrize(
    ("specifications", "environment", "message"),
    [
        (["Authorization"], {}, "NAME=ENVIRONMENT_VARIABLE"),
        (["=AUTH_HEADER"], {"AUTH_HEADER": "token"}, "header name"),
        (["Authorization=AUTH_HEADER"], {}, "AUTH_HEADER"),
        (["Authorization=AUTH_HEADER"], {"AUTH_HEADER": "  "}, "AUTH_HEADER"),
        (["Authorization=FIRST", "authorization=SECOND"], {"FIRST": "one", "SECOND": "two"}, "duplicate"),
    ],
)
def test_invalid_header_configuration_is_rejected(
    specifications: list[str],
    environment: Mapping[str, str],
    message: str,
) -> None:
    """Reject malformed, duplicate, or missing authentication headers."""
    with pytest.raises(ValueError, match=message):
        inspect_mcp.headers_from_environment(specifications, environment)


def test_tool_report_shows_descriptions_arguments_and_full_schema() -> None:
    """Render tool and argument descriptions while retaining the complete schema."""
    tool = inspect_mcp.ToolDescription(
        name="invoke_agent",
        description="Send a message to the agent.",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "User-authored request."},
                "conversation_id": {"type": "string", "description": "Conversation to continue."},
            },
            "required": ["message"],
        },
    )

    report = inspect_mcp.render_tools([tool])

    assert "invoke_agent" in report
    assert "Send a message to the agent." in report
    assert "message (string, required)" in report
    assert "User-authored request." in report
    assert "conversation_id (string, optional)" in report
    assert "Conversation to continue." in report
    assert '"required": [\n      "message"\n    ]' in report


class FakeHttpClient:
    """Capture request headers and whether the HTTP client was closed."""

    def __init__(self, headers: Mapping[str, str], verify: bool) -> None:
        self.headers = dict(headers)
        self.verify = verify
        self.closed = False

    async def __aenter__(self) -> FakeHttpClient:
        """Open the fake HTTP client."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Record client cleanup."""
        self.closed = True


class FakeClientSession:
    """Return one declared tool and record MCP methods called by the inspector."""

    def __init__(self, read_stream: object, write_stream: object) -> None:
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.calls: list[str] = []
        self.closed = False

    async def __aenter__(self) -> FakeClientSession:
        """Open the fake MCP session."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Record MCP session cleanup."""
        self.closed = True

    async def initialize(self) -> None:
        """Record protocol initialization."""
        self.calls.append("initialize")

    async def list_tools(self) -> SimpleNamespace:
        """Return the fake server's exposed tool catalogue."""
        self.calls.append("list_tools")
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="invoke_agent",
                    description="Send a message to the agent.",
                    inputSchema={"type": "object", "properties": {"message": {"type": "string"}}},
                )
            ]
        )

    async def call_tool(self, *_: object, **__: object) -> None:
        """Fail if the diagnostic client attempts to invoke an operation."""
        pytest.fail("the MCP inspector must not invoke a tool")


@pytest.mark.asyncio
async def test_inspection_lists_tools_and_closes_the_http_and_mcp_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inspect with configured headers, list only, and close both resources."""
    state: dict[str, Any] = {}

    def build_http_client(*, headers: Mapping[str, str], verify: bool) -> FakeHttpClient:
        """Create and retain the fake HTTP client for assertions."""
        client = FakeHttpClient(headers, verify)
        state["http_client"] = client
        return client

    @asynccontextmanager
    async def connect(url: str, *, http_client: FakeHttpClient) -> AsyncIterator[tuple[object, object, object]]:
        """Capture transport inputs and yield fake MCP streams."""
        state["url"] = url
        state["request_headers"] = http_client.headers
        yield object(), object(), object()

    def build_session(read_stream: object, write_stream: object) -> FakeClientSession:
        """Create and retain the fake MCP session for assertions."""
        session = FakeClientSession(read_stream, write_stream)
        state["session"] = session
        return session

    monkeypatch.setattr(httpx, "AsyncClient", build_http_client)
    monkeypatch.setattr(inspect_mcp, "streamable_http_client", connect)
    monkeypatch.setattr(inspect_mcp, "ClientSession", build_session)

    tools = await inspect_mcp.inspect_tools("https://agent.test/mcp", {"X-API-Key": "secret"})

    assert [tool.name for tool in tools] == ["invoke_agent"]
    assert state["url"] == "https://agent.test/mcp"
    assert state["request_headers"] == {"X-API-Key": "secret"}
    assert state["http_client"].verify is True
    assert state["http_client"].closed is True
    assert state["session"].calls == ["initialize", "list_tools"]
    assert state["session"].closed is True


def test_failed_inspection_returns_nonzero_without_printing_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report a failed list request without exposing authentication values."""
    auth_value = "Bearer highly-sensitive-token"
    failed_state: dict[str, Any] = {}

    def build_http_client(*, headers: Mapping[str, str], verify: bool) -> FakeHttpClient:
        """Create and retain the HTTP client used for the failed request."""
        client = FakeHttpClient(headers, verify)
        failed_state["http_client"] = client
        return client

    @asynccontextmanager
    async def connect(url: str, *, http_client: FakeHttpClient) -> AsyncIterator[tuple[object, object, object]]:
        """Track cleanup when an MCP request raises."""
        failed_state["transport_opened"] = True
        try:
            yield object(), object(), object()
        finally:
            failed_state["transport_closed"] = True

    class FailedSession(FakeClientSession):
        """Raise a fake remote error that includes the configured header value."""

        async def __aenter__(self) -> FailedSession:
            """Record the session so failure cleanup can be asserted."""
            failed_state["session"] = self
            return self

        async def list_tools(self) -> SimpleNamespace:
            """Simulate a server rejection that includes the request header."""
            raise RuntimeError(f"server rejected {auth_value}")

    monkeypatch.setattr(httpx, "AsyncClient", build_http_client)
    monkeypatch.setattr(inspect_mcp, "streamable_http_client", connect)
    monkeypatch.setattr(inspect_mcp, "ClientSession", FailedSession)

    exit_code = inspect_mcp.main(
        ["--url", "https://agent.test/mcp", "--header", "Authorization=MAIL_AUTH"],
        environment={"MAIL_AUTH": auth_value},
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert auth_value not in captured.out
    assert auth_value not in captured.err
    assert failed_state["http_client"].closed is True
    assert failed_state["transport_closed"] is True
    assert failed_state["session"].closed is True
