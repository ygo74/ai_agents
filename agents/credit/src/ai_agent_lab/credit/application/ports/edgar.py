"""Replaceable issuer discovery boundary; implementations must use MCP."""

from typing import Protocol

from ai_agent_lab.credit.domain.models import Company, QueryType, SearchResults, Source


class EdgarPort(Protocol):
    """Search for issuers and retrieve an authoritative profile by CIK."""

    async def search(self, query: str, query_type: QueryType) -> SearchResults:
        """Return candidates and retrieval limits for the normalized query."""
        ...

    async def profile(self, cik: str) -> tuple[Company, Source]:
        """Retrieve one SEC profile, which must still be checked against cik."""
        ...
