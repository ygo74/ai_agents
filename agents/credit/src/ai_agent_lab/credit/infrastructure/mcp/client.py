"""Official EdgarTools 6.3 MCP dialect using runtime-owned connection mechanics."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, ClassVar, Protocol, TypeVar
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ygo74.agent_runtime.domains.configuration.manifest_schemas import JsonSchemaValidator
from ygo74.agent_runtime.domains.contracts.invocation_context import AgentInvocationContextScope
from ygo74.agent_runtime.domains.mcp.binding import McpConnection
from ygo74.agent_runtime.domains.mcp.mcp_errors import McpToolUnavailableError

from ai_agent_lab.credit.application.ports.edgar import EdgarPort
from ai_agent_lab.credit.domain.errors import EdgarAccessError, EdgarNoMatchError
from ai_agent_lab.credit.domain.models import Company, ErrorCode, Listing, QueryType, SearchResults, Source

logger = logging.getLogger(__name__)
T = TypeVar("T")


class SessionProvider(Protocol):
    """Connection scope injected for reproducible MCP transport tests."""

    async def session(self) -> ClientSession:
        """Open or reuse a session."""
        ...

    async def aclose(self) -> None:
        """Release the connection and its subprocess/streams."""
        ...


class RuntimeSessionProvider(SessionProvider):
    """Adapt the public runtime connection without recreating its mechanics."""

    def __init__(self, connection: McpConnection) -> None:
        """Inject the configured runtime-owned connection."""
        self._connection = connection

    async def session(self) -> ClientSession:
        """Delegate lazy connection initialization to the runtime."""
        return await self._connection.session()

    async def aclose(self) -> None:
        """Delegate subprocess/HTTP cleanup to the runtime."""
        await self._connection.aclose()


class McpGateway:
    """Discover actual tool schemas and bound read-only calls and transient retries."""

    _PROPERTIES: ClassVar[dict[str, set[str]]] = {
        "edgar_search": {"query", "search_type", "limit"},
        "edgar_company": {"identifier", "include"},
    }

    def __init__(
        self, provider: SessionProvider, *, timeout: float = 30, max_attempts: int = 2, retry_delay: float = 1
    ) -> None:
        """Inject transport and bounded deadline/retry parameters."""
        self._provider = provider
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._schemas: dict[str, dict[str, Any]] = {}

    async def discover(self) -> dict[str, dict[str, Any]]:
        """Verify required tools exist and support the parameters this dialect sends."""
        session = await self._provider.session()
        listed = await session.list_tools()
        schemas = {tool.name: tool.inputSchema for tool in listed.tools}
        for name, required in self._PROPERTIES.items():
            schema = schemas.get(name)
            if not isinstance(schema, dict) or not required <= set(schema.get("properties", {})):
                raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        self._schemas = {name: schemas[name] for name in self._PROPERTIES}
        return self._schemas

    async def call(self, tool: str, arguments: dict[str, object]) -> dict[str, Any]:
        """Call only identification tools, validating actual input schemas first."""
        if tool not in self._PROPERTIES:
            raise EdgarAccessError(ErrorCode.INVALID_INPUT)
        return await self._retry(lambda: self._call_once(tool, arguments), tool)

    async def _call_once(self, tool: str, arguments: dict[str, object]) -> dict[str, Any]:
        """Discover before calling; validate both transport and business envelopes."""
        if not self._schemas:
            await self.discover()
        try:
            JsonSchemaValidator.validate(arguments, json.dumps(self._schemas[tool]), path=Path(tool))
        except ValueError as error:
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE) from error
        session = await self._provider.session()
        wire = await session.call_tool(tool, arguments)
        payload = self._payload(wire)
        if payload.get("success") is not True:
            self._tool_error(payload)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        return data

    @staticmethod
    def _payload(wire: CallToolResult) -> dict[str, Any]:
        """Accept official JSON text or structuredContent; never execute tool suggestions."""
        if wire.isError:
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        payload: Any = wire.structuredContent
        if payload is None:
            texts = [item.text for item in wire.content if item.type == "text"]
            if len(texts) != 1:
                raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
            try:
                payload = json.loads(texts[0])
            except json.JSONDecodeError as error:
                raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE) from error
        if not isinstance(payload, dict):
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        return payload

    @staticmethod
    def _tool_error(payload: dict[str, Any]) -> None:
        """Categorize upstream failures conservatively without leaking free text."""
        code = str(payload.get("error_code", "")).lower()
        message = str(payload.get("error", "")).lower()
        if code == "company_not_found":
            raise EdgarNoMatchError
        # Official server sometimes returns only free text; unknown failures are not no-match.
        if code in {"rate_limit", "429", "service_unavailable", "503"}:
            delay = payload.get("retry_after")
            raise EdgarAccessError(
                ErrorCode.SEC_ACCESS_ERROR,
                transient=True,
                retry_after=float(delay) if isinstance(delay, (int, float)) and delay >= 0 else None,
            )
        if any(word in message for word in ("sec", "403", "429", "http", "connection", "timeout", "rate limit")):
            raise EdgarAccessError(ErrorCode.SEC_ACCESS_ERROR)
        raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)

    async def _retry(self, action: Callable[[], Awaitable[T]], tool: str) -> T:
        """Bound each attempt and preserve server retry delays without truncating them."""
        context = AgentInvocationContextScope.current()
        correlation = context.request_id if context else uuid4().hex
        for attempt in range(self._max_attempts):
            try:
                started = monotonic()
                async with asyncio.timeout(self._timeout):
                    result = await action()
            except TimeoutError:
                failure = EdgarAccessError(ErrorCode.TIMEOUT, transient=True)
            except (OSError, httpx.TransportError, McpToolUnavailableError):
                failure = EdgarAccessError(ErrorCode.SERVER_UNAVAILABLE, transient=True)
            except McpError as error:
                failure = self._protocol_failure(error)
            except EdgarAccessError as error:
                failure = error
            else:
                logger.info(
                    "credit_mcp correlation_id=%s tool=%s attempt=%s status=success duration_ms=%s",
                    correlation,
                    tool,
                    attempt + 1,
                    round((monotonic() - started) * 1000),
                )
                return result
            logger.warning("credit_mcp correlation_id=%s attempt=%s code=%s", correlation, attempt + 1, failure.code)
            if not failure.transient or attempt + 1 == self._max_attempts:
                raise failure
            await self._pause(failure, attempt)
        raise EdgarAccessError(ErrorCode.SERVER_UNAVAILABLE)

    @staticmethod
    def _protocol_failure(error: McpError) -> EdgarAccessError:
        """Recognize the SDK's typed HTTP 408 timeout without parsing free-text messages."""
        if error.error.code == 408:
            return EdgarAccessError(ErrorCode.TIMEOUT, transient=True)
        return EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)

    async def _pause(self, failure: EdgarAccessError, attempt: int) -> None:
        """Honor server backoff or stop rather than retry earlier than requested."""
        delay = failure.retry_after if failure.retry_after is not None else self._retry_delay * (2**attempt)
        if delay > self._timeout:
            raise failure
        await asyncio.sleep(delay)

    async def aclose(self) -> None:
        """Close on the same task that opened the runtime session."""
        await self._provider.aclose()


class CandidateWire(BaseModel):
    """Allow upstream informational fields but use only typed identity metadata."""

    model_config = ConfigDict(extra="ignore")
    cik: str
    name: str
    ticker: str | None = None


class ProfileWire(BaseModel):
    """Official profile; industry is SEC SIC description, never inferred sector."""

    model_config = ConfigDict(extra="ignore")
    cik: str
    name: str
    tickers: list[str] = Field(default_factory=list)
    sic: str | int | None = None
    industry: str | None = None


class EdgarMcpAdapter(EdgarPort):
    """Translate the official search/profile tools into business contracts."""

    def __init__(self, gateway: McpGateway, *, search_limit: int = 50) -> None:
        """Inject MCP calls and an explicit maximum candidate count."""
        self._gateway = gateway
        self._search_limit = search_limit

    async def search(self, query: str, query_type: QueryType) -> SearchResults:
        """Retrieve company matches and report the server's finite search limit."""
        if query_type not in {QueryType.NAME, QueryType.TICKER}:
            raise EdgarAccessError(ErrorCode.INVALID_INPUT)
        data = await self._gateway.call(
            "edgar_search", {"query": query, "search_type": "companies", "limit": self._search_limit}
        )
        rows = data.get("companies")
        if not isinstance(rows, list):
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        source = self._source("ticker-reference", "https://www.sec.gov/files/company_tickers.json", "company_reference")
        companies = []
        for row in rows:
            if not isinstance(row, dict):
                raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
            if "error" in row:
                McpGateway._tool_error(row)
            try:
                candidate = CandidateWire.model_validate(row)
                listings = [Listing(ticker=candidate.ticker)] if candidate.ticker else []
                companies.append(
                    Company(
                        legal_name=candidate.name,
                        cik=candidate.cik,
                        listings=listings,
                        field_sources={
                            "legal_name": [source.id],
                            "cik": [source.id],
                            **({"listings": [source.id]} if listings else {}),
                        },
                    )
                )
            except ValidationError as error:
                raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE) from error
        truncated = len(rows) >= self._search_limit
        warnings = [
            "Company-name matching uses the SEC ticker reference; non-listed issuers may be absent.",
            "Source retrieval timestamp is MCP retrieval time; the server may use cached SEC data.",
        ]
        if truncated:
            warnings.append(
                "Search limit reached; additional issuers may be omitted. Refine the query or select a CIK."
            )
        return SearchResults(companies=companies, sources=[source], warnings=warnings, truncated=truncated)

    async def profile(self, cik: str) -> tuple[Company, Source]:
        """Request only the profile and attach canonical SEC metadata provenance."""
        data = await self._gateway.call("edgar_company", {"identifier": cik, "include": ["profile"]})
        try:
            profile = ProfileWire.model_validate(data.get("profile"))
            company = Company(
                legal_name=profile.name,
                cik=profile.cik,
                listings=[Listing(ticker=t) for t in profile.tickers],
                sic_code=str(profile.sic) if profile.sic is not None else None,
                sic_description=profile.industry,
            )
        except ValidationError as error:
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE) from error
        if company.cik != cik or (data.get("cik") is not None and str(data["cik"]).zfill(10) != cik):
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        if data.get("company") is not None and data["company"] != company.legal_name:
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        source = self._source(f"submissions-{cik}", f"https://data.sec.gov/submissions/CIK{cik}.json", "submissions")
        for field in ("legal_name", "cik", "listings", "sic_code", "sic_description"):
            if getattr(company, field):
                company.field_sources[field] = [source.id]
        return company, source

    @staticmethod
    def _source(identifier: str, url: str, resource: str) -> Source:
        """Timestamp successful MCP retrieval; do not invent publication metadata."""
        return Source(id=identifier, url=url, resource_type=resource, retrieved_at=datetime.now(UTC))
