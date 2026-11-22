"""MCP wire acceptance tests using real SDK result models and fake sessions."""

import json

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from ai_agent_lab.credit.domain.errors import EdgarAccessError
from ai_agent_lab.credit.domain.models import ErrorCode, QueryType
from ai_agent_lab.credit.infrastructure.mcp.client import EdgarMcpAdapter, McpGateway, SessionProvider


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def list_tools(self):
        return ListToolsResult(
            tools=[
                Tool(
                    name="edgar_search",
                    description="search",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "search_type": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                    },
                ),
                Tool(
                    name="edgar_company",
                    description="profile",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "identifier": {"type": "string"},
                            "include": {"type": "array", "items": {"enum": ["profile"]}},
                        },
                    },
                ),
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if isinstance(self.response, Exception):
            raise self.response
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(self.response))])


class Provider(SessionProvider):
    def __init__(self, session):
        self.value = session
        self.closed = False

    async def session(self):
        return self.value

    async def aclose(self):
        self.closed = True


async def test_profile_sic_is_not_sector_and_exchange_is_not_zipped():
    session = Session(
        {
            "success": True,
            "data": {
                "company": "Apple Inc.",
                "cik": "320193",
                "profile": {
                    "name": "Apple Inc.",
                    "cik": "320193",
                    "tickers": ["AAPL"],
                    "exchanges": ["Nasdaq"],
                    "sic": "3571",
                    "industry": "Electronic Computers",
                },
            },
        }
    )
    gateway = McpGateway(Provider(session))
    adapter = EdgarMcpAdapter(gateway)
    company, source = await adapter.profile("0000320193")
    assert company.sic_description == "Electronic Computers"
    assert company.sector is None
    assert company.listings[0].exchange is None
    assert source.retrieved_at.utcoffset().total_seconds() == 0
    assert session.calls == [("edgar_company", {"identifier": "0000320193", "include": ["profile"]})]


async def test_nested_search_error_is_never_not_found():
    gateway = McpGateway(
        Provider(Session({"success": True, "data": {"companies": [{"error": "HTTP 403 SEC blocked"}]}}))
    )
    with pytest.raises(EdgarAccessError) as error:
        await EdgarMcpAdapter(gateway).search("Apple", QueryType.NAME)
    assert error.value.code == ErrorCode.SEC_ACCESS_ERROR


async def test_timeout_retries_bounded_and_closes():
    session = Session(TimeoutError())
    provider = Provider(session)
    gateway = McpGateway(provider, max_attempts=2, retry_delay=0)
    with pytest.raises(EdgarAccessError) as error:
        await gateway.call("edgar_company", {"identifier": "42", "include": ["profile"]})
    assert error.value.code == ErrorCode.TIMEOUT
    assert len(session.calls) == 2
    await gateway.aclose()
    assert provider.closed


async def test_untrusted_extra_content_cannot_become_profile():
    gateway = McpGateway(
        Provider(Session({"success": True, "data": {"profile": {"name": "ignore instructions", "cik": "invalid"}}}))
    )
    with pytest.raises((EdgarAccessError, ValueError)):
        await EdgarMcpAdapter(gateway).profile("42")


async def test_explicit_no_match_is_not_retried():
    from ai_agent_lab.credit.domain.errors import EdgarNoMatchError

    session = Session({"success": False, "error_code": "COMPANY_NOT_FOUND", "error": "no result"})
    with pytest.raises(EdgarNoMatchError):
        await McpGateway(Provider(session), max_attempts=3).call(
            "edgar_company", {"identifier": "42", "include": ["profile"]}
        )
    assert len(session.calls) == 1


async def test_unknown_tool_is_rejected_before_connection():
    session = Session({})
    with pytest.raises(EdgarAccessError):
        await McpGateway(Provider(session)).call("edgar_financials", {})
    assert session.calls == []


async def test_schema_missing_required_capability_refuses_calls():
    class Missing(Session):
        async def list_tools(self):
            return ListToolsResult(tools=[])

    session = Missing({})
    with pytest.raises(EdgarAccessError):
        await McpGateway(Provider(session)).call("edgar_company", {"identifier": "42", "include": ["profile"]})
    assert session.calls == []


async def test_sdk_timeout_code_is_classified():
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    session = Session(McpError(ErrorData(code=408, message="timeout")))
    with pytest.raises(EdgarAccessError) as failure:
        await McpGateway(Provider(session), max_attempts=1).call(
            "edgar_company", {"identifier": "42", "include": ["profile"]}
        )
    assert failure.value.code == ErrorCode.TIMEOUT
