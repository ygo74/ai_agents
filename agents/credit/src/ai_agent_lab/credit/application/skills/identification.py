"""Deterministic issuer identification; the model never decides the identity."""

import logging
from collections.abc import Mapping
from uuid import uuid4

from pydantic import ValidationError
from ygo74.agent_runtime.domains.contracts.invocation_context import AgentInvocationContext, AgentInvocationContextScope

from ai_agent_lab.credit.application.ports.edgar import EdgarPort
from ai_agent_lab.credit.domain.errors import EdgarAccessError, EdgarNoMatchError
from ai_agent_lab.credit.domain.models import (
    Company,
    ErrorCode,
    IdentificationError,
    IdentificationRequest,
    IdentificationResult,
    QueryType,
    SearchResults,
    Status,
)

logger = logging.getLogger(__name__)


class IdentificationSkill:
    """Validate, deduplicate, require explicit selection, then confirm a SEC profile."""

    def __init__(self, edgar: EdgarPort) -> None:
        """Inject the MCP-facing issuer port."""
        self._edgar = edgar

    async def execute(self, payload: Mapping[str, object]) -> IdentificationResult:
        """Identify from structured input, returning safe errors for known failures."""
        context = AgentInvocationContextScope.current() or AgentInvocationContext(request_id=uuid4().hex)
        correlation = context.request_id
        try:
            request = IdentificationRequest.model_validate(payload)
        except ValidationError:
            return self._invalid(payload)
        logger.info("credit_identification correlation_id=%s stage=start", correlation)
        try:
            with AgentInvocationContextScope.bind(context):
                result = await self._identify(request)
        except EdgarNoMatchError:
            result = IdentificationResult(
                status=Status.NOT_FOUND,
                query=request.query,
                query_type=request.query_type,
                warnings=["The server explicitly reported no match; this does not prove company nonexistence."],
            )
        except EdgarAccessError as failure:
            result = self._error(request, failure.code)
        except (ValidationError, ValueError, KeyError):
            result = self._error(request, ErrorCode.INVALID_MCP_RESPONSE)
        logger.info("credit_identification correlation_id=%s status=%s", correlation, result.status)
        return result

    async def _identify(self, request: IdentificationRequest) -> IdentificationResult:
        """Separate candidate discovery from profile confirmation to prevent arbitrary choices."""
        if request.query_type == QueryType.CIK:
            if request.selected_cik and request.selected_cik != request.query:
                return self._error(request, ErrorCode.INVALID_INPUT)
            return await self._confirmed(request, request.query, SearchResults())
        found = await self._edgar.search(request.query, request.query_type)
        candidates = self._deduplicate(found.companies, request)
        if request.selected_cik:
            if request.selected_cik not in {c.cik for c in candidates}:
                return self._error(request, ErrorCode.INVALID_INPUT)
            return await self._confirmed(request, request.selected_cik, found)
        if not candidates:
            return IdentificationResult(
                status=Status.NOT_FOUND,
                query=request.query,
                query_type=request.query_type,
                sources=found.sources,
                warnings=[
                    *found.warnings,
                    "No match in this EDGAR search; this does not establish that the company does not exist.",
                ],
            )
        if len(candidates) > 1 or found.truncated:
            return IdentificationResult(
                status=Status.AMBIGUOUS,
                query=request.query,
                query_type=request.query_type,
                candidates=candidates,
                sources=found.sources,
                warnings=[*found.warnings, "Select a candidate CIK; no issuer has been confirmed."],
            )
        return await self._confirmed(request, candidates[0].cik, found)

    @staticmethod
    def _deduplicate(companies: list[Company], request: IdentificationRequest) -> list[Company]:
        """Group by CIK before ticker filtering, preserving all known issuer listings."""
        merged: dict[str, Company] = {}
        for company in companies:
            previous = merged.get(company.cik)
            if previous is None:
                merged[company.cik] = company.model_copy(deep=True)
                continue
            if previous.legal_name.casefold() != company.legal_name.casefold():
                raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
            for listing in company.listings:
                if listing not in previous.listings:
                    previous.listings.append(listing)
            for field, refs in company.field_sources.items():
                previous.field_sources[field] = list(dict.fromkeys([*previous.field_sources.get(field, []), *refs]))
        if request.query_type == QueryType.TICKER:
            return [
                c for c in merged.values() if any(listing.ticker.upper() == request.query for listing in c.listings)
            ]
        return list(merged.values())

    async def _confirmed(self, request: IdentificationRequest, cik: str, found: SearchResults) -> IdentificationResult:
        """Retrieve by CIK and reject mismatches before attaching any confirmed profile."""
        company, source = await self._edgar.profile(cik)
        if company.cik != cik:
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        if request.query_type == QueryType.TICKER and not any(
            listing.ticker.upper() == request.query for listing in company.listings
        ):
            raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
        self._merge_search_listings(company, found, request)
        sources = {s.id: s for s in [*found.sources, source]}
        warnings = [
            *found.warnings,
            "Source timestamps describe MCP retrieval; SEC data may come from the server cache.",
        ]
        for field in ("listings", "sic_code", "sic_description", "sector"):
            if not getattr(company, field):
                warnings.append(f"SEC metadata unavailable: {field}.")
        if any(listing.exchange is None for listing in company.listings):
            warnings.append("Exchange association unavailable; ticker/exchange lists are not paired by position.")
        return IdentificationResult(
            status=Status.IDENTIFIED,
            query=request.query,
            query_type=request.query_type,
            company=company,
            sources=list(sources.values()),
            warnings=warnings,
        )

    def _merge_search_listings(self, company: Company, found: SearchResults, request: IdentificationRequest) -> None:
        """Merge listings only for a profile whose CIK was verified."""
        # Merge search listings only after both identities agree; keep their own references.
        for candidate in self._deduplicate(found.companies, request):
            if candidate.cik != company.cik:
                continue
            if candidate.legal_name.casefold() != company.legal_name.casefold():
                raise EdgarAccessError(ErrorCode.INVALID_MCP_RESPONSE)
            for listing in candidate.listings:
                if listing not in company.listings:
                    company.listings.append(listing)
            if candidate.listings:
                company.field_sources["listings"] = list(
                    dict.fromkeys(
                        [*company.field_sources.get("listings", []), *candidate.field_sources.get("listings", [])]
                    )
                )

    @staticmethod
    def _error(request: IdentificationRequest, code: ErrorCode) -> IdentificationResult:
        """Return a stable category without upstream content."""
        messages = {
            ErrorCode.INVALID_INPUT: "Invalid input or selected CIK outside the search candidates.",
            ErrorCode.SERVER_UNAVAILABLE: "EDGAR MCP server unavailable.",
            ErrorCode.TIMEOUT: "EDGAR MCP deadline exceeded.",
            ErrorCode.SEC_ACCESS_ERROR: "SEC access failed; no identity has been confirmed.",
            ErrorCode.INVALID_MCP_RESPONSE: "MCP response incomplete or inconsistent; no identity confirmed.",
        }
        return IdentificationResult(
            status=Status.ERROR,
            query=request.query,
            query_type=request.query_type,
            error=IdentificationError(code=code, message=messages[code]),
        )

    @classmethod
    def _invalid(cls, payload: Mapping[str, object]) -> IdentificationResult:
        """Preserve only safe typed input metadata when validation fails."""
        query = payload.get("query")
        kind = payload.get("query_type", "auto")
        return IdentificationResult(
            status=Status.ERROR,
            query=query if isinstance(query, str) else "",
            query_type=QueryType(kind) if isinstance(kind, str) and kind in QueryType else QueryType.AUTO,
            error=IdentificationError(code=ErrorCode.INVALID_INPUT, message="Invalid query, query type or CIK."),
        )
