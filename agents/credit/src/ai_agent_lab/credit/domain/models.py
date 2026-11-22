"""Validated SEC identification contracts and deterministic value normalization."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_cik(value: str) -> str:
    """Normalize a positive ASCII CIK of at most ten digits without numeric output."""
    cleaned = value.strip()
    if not cleaned.isascii() or not cleaned.isdigit() or len(cleaned) > 10 or int(cleaned) == 0:
        raise ValueError("CIK must contain 1-10 ASCII digits and be nonzero")
    return cleaned.zfill(10)


class QueryType(StrEnum):
    """Supported analyst search modes."""

    NAME = "name"
    TICKER = "ticker"
    CIK = "cik"
    AUTO = "auto"


class Status(StrEnum):
    """Mutually exclusive identification outcomes."""

    IDENTIFIED = "identified"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    ERROR = "error"


class ErrorCode(StrEnum):
    """Stable machine-readable failure categories."""

    INVALID_INPUT = "invalid_input"
    SERVER_UNAVAILABLE = "server_unavailable"
    TIMEOUT = "timeout"
    SEC_ACCESS_ERROR = "sec_access_error"
    INVALID_MCP_RESPONSE = "invalid_mcp_response"


class Contract(BaseModel):
    """Reject unknown fields at every business boundary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class IdentificationRequest(Contract):
    """Analyst input; selected CIK is checked against a fresh search."""

    query: Annotated[str, Field(min_length=1, max_length=256)]
    query_type: QueryType = QueryType.AUTO
    selected_cik: str | None = None

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        """Refuse whitespace-only queries."""
        if not value.strip():
            raise ValueError("query is empty")
        return value.strip()

    @field_validator("selected_cik")
    @classmethod
    def clean_selection(cls, value: str | None) -> str | None:
        """Normalize the optional explicit selection."""
        return normalize_cik(value) if value is not None else None

    @model_validator(mode="after")
    def resolve_query(self) -> Self:
        """Resolve auto once; deterministic ticker syntax does not use a model."""
        kind = self.query_type
        if kind == QueryType.AUTO:
            if self.query.isascii() and self.query.isdigit():
                kind = QueryType.CIK
            elif (
                self.query.isascii()
                and len(self.query) <= 10
                and all(c.isalpha() or c in ".-" for c in self.query)
                and " " not in self.query
            ):
                kind = QueryType.TICKER
            else:
                kind = QueryType.NAME
        query = normalize_cik(self.query) if kind == QueryType.CIK else self.query
        if kind == QueryType.TICKER:
            query = query.upper()
        # Avoid assignment validation recursion inside model validation.
        object.__setattr__(self, "query_type", kind)
        object.__setattr__(self, "query", query)
        return self


class Listing(Contract):
    """A ticker and its explicitly known exchange, if any."""

    ticker: Annotated[str, Field(min_length=1)]
    exchange: str | None = None


class Source(Contract):
    """SEC resource retrieved via MCP; retrieved_at is not a publication date."""

    id: Annotated[str, Field(min_length=1)]
    url: str
    resource_type: Annotated[str, Field(min_length=1)]
    retrieved_at: datetime
    published_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def sec_url(cls, value: str) -> str:
        """Require a canonical HTTPS SEC URL with no embedded credentials."""
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.hostname not in {"www.sec.gov", "data.sec.gov"}:
            raise ValueError("source must be a SEC HTTPS URL")
        if parts.username or parts.password or parts.port not in {None, 443}:
            raise ValueError("source URL contains invalid authority")
        return value

    @field_validator("retrieved_at", "published_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        """Require UTC-aware timestamps rather than silently assuming a timezone."""
        offset = value.utcoffset() if value is not None else None
        if value is not None and (offset is None or offset.total_seconds() != 0):
            raise ValueError("source timestamps must be UTC")
        return value


class Company(Contract):
    """SEC issuer identity, keeping SIC separate from an independent sector."""

    legal_name: Annotated[str, Field(min_length=1)]
    cik: str
    listings: list[Listing] = Field(default_factory=list)
    sic_code: str | None = None
    sic_description: str | None = None
    sector: str | None = None
    sector_origin: str | None = None
    field_sources: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("cik")
    @classmethod
    def cik_value(cls, value: str) -> str:
        """Normalize SEC identity even when an upstream tool omits padding."""
        return normalize_cik(value)

    @field_validator("legal_name")
    @classmethod
    def legal_name_value(cls, value: str) -> str:
        """Refuse a profile without a usable SEC legal name."""
        if not value.strip():
            raise ValueError("SEC legal name missing")
        return value.strip()

    @model_validator(mode="after")
    def sector_provenance(self) -> Self:
        """An independent sector must always carry its explicit provenance."""
        if (self.sector is None) != (self.sector_origin is None):
            raise ValueError("sector requires sector_origin")
        return self


class IdentificationError(Contract):
    """Safe error information without upstream content or credentials."""

    code: ErrorCode
    message: str


class SearchResults(Contract):
    """Port search data including explicit completeness limitations."""

    companies: list[Company] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False


class IdentificationResult(Contract):
    """Validated result; sources must ground every populated profile field."""

    status: Status
    query: str
    query_type: QueryType
    company: Company | None = None
    candidates: list[Company] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: IdentificationError | None = None

    @model_validator(mode="after")
    def consistency(self) -> Self:
        """Check state shape and source references together before emitting output."""
        if (self.status == Status.IDENTIFIED) != (self.company is not None):
            raise ValueError("identified requires company exclusively")
        if (self.status == Status.ERROR) != (self.error is not None):
            raise ValueError("error requires error details exclusively")
        if (self.status == Status.AMBIGUOUS) != bool(self.candidates):
            raise ValueError("candidates belong only to ambiguous results")
        ids = {s.id for s in self.sources}
        if len(ids) != len(self.sources):
            raise ValueError("duplicate source identifiers")
        profiles = [self.company] if self.company else self.candidates
        if len({c.cik for c in profiles}) != len(profiles):
            raise ValueError("duplicate candidate CIK")
        for profile in profiles:
            self._validate_sources(profile, ids)
        return self

    @staticmethod
    def _validate_sources(profile: Company, ids: set[str]) -> None:
        """Check each populated identity field against the response source registry."""
        allowed = {"legal_name", "cik", "listings", "sic_code", "sic_description", "sector", "sector_origin"}
        if not set(profile.field_sources) <= allowed:
            raise ValueError("unknown profile field source")
        if any(not refs or not set(refs) <= ids for refs in profile.field_sources.values()):
            raise ValueError("unknown or empty source references")
        for field in allowed:
            value = getattr(profile, field)
            if value is None or value == []:
                continue
            refs = profile.field_sources.get(field, [])
            if not refs or not set(refs) <= ids:
                raise ValueError(f"missing or invalid sources for {field}")
