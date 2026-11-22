"""Deterministic identification acceptance cases, independent of MCP and models."""

from datetime import UTC, datetime

import pytest

from ai_agent_lab.credit.application.ports.edgar import EdgarPort
from ai_agent_lab.credit.application.skills.identification import IdentificationSkill
from ai_agent_lab.credit.domain.models import Company, IdentificationRequest, SearchResults, Source


def company(cik="320193", name="Apple Inc.", tickers=()):
    source = Source(
        id=f"sec-{cik}",
        url=f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
        resource_type="submissions",
        retrieved_at=datetime.now(UTC),
    )
    return Company(
        legal_name=name,
        cik=cik,
        listings=[{"ticker": t} for t in tickers],
        field_sources={"legal_name": [source.id], "cik": [source.id], **({"listings": [source.id]} if tickers else {})},
    ), source


class FakeEdgar(EdgarPort):
    """Return fixed candidates and count calls to prove validation occurs first."""

    def __init__(self, companies):
        self.companies = companies
        self.calls = []

    async def search(self, query, query_type):
        self.calls.append(("search", query))
        return SearchResults(companies=[c for c, s in self.companies], sources=[s for c, s in self.companies])

    async def profile(self, cik):
        self.calls.append(("profile", cik))
        return next((c, s) for c, s in self.companies if c.cik == cik)


@pytest.mark.parametrize("query,kind", [("", "auto"), ("abc", "cik"), ("0", "cik"), ("12345678901", "cik")])
async def test_invalid_input_does_not_call_mcp(query, kind):
    fake = FakeEdgar([])
    result = await IdentificationSkill(fake).execute({"query": query, "query_type": kind})
    assert result.status == "error"
    assert result.error.code == "invalid_input"
    assert fake.calls == []


@pytest.mark.parametrize(
    "query,kind", [("aapl", "ticker"), ("320193", "cik"), ("0000320193", "cik"), ("Apple", "name")]
)
async def test_identification(query, kind):
    fake = FakeEdgar([company(tickers=("AAPL",))])
    result = await IdentificationSkill(fake).execute({"query": query, "query_type": kind})
    assert result.status == "identified"
    assert result.company.cik == "0000320193"
    assert result.company.sector is None
    assert result.sources
    assert result.warnings
    assert fake.calls[-1] == ("profile", "0000320193")


async def test_ambiguity_selection_and_foreign_selection():
    fake = FakeEdgar([company(tickers=("ABC",)), company("42", "Other Inc.", ("ABC",))])
    skill = IdentificationSkill(fake)
    ambiguous = await skill.execute({"query": "abc", "query_type": "ticker"})
    assert ambiguous.status == "ambiguous"
    assert ambiguous.company is None
    assert len(ambiguous.candidates) == 2
    assert all(c[0] != "profile" for c in fake.calls)
    selected = await skill.execute({"query": "abc", "query_type": "ticker", "selected_cik": "42"})
    assert selected.company.cik == "0000000042"
    rejected = await skill.execute({"query": "abc", "query_type": "ticker", "selected_cik": "99"})
    assert rejected.error.code == "invalid_input"


async def test_duplicates_merge_and_missing_metadata():
    fake = FakeEdgar([company(tickers=("AAPL",)), company(tickers=("APPL",))])
    result = await IdentificationSkill(fake).execute({"query": "Apple", "query_type": "name"})
    assert result.status == "identified"
    assert len(result.company.listings) == 2
    no_ticker = await IdentificationSkill(FakeEdgar([company()])).execute({"query": "Apple", "query_type": "name"})
    assert no_ticker.status == "identified"
    assert no_ticker.company.listings == []


async def test_no_result_is_not_proof_of_nonexistence():
    result = await IdentificationSkill(FakeEdgar([])).execute({"query": "unknown", "query_type": "name"})
    assert result.status == "not_found"
    assert result.warnings


def test_request_rejects_unknown_fields():
    with pytest.raises(ValueError):
        IdentificationRequest(query="AAPL", instructions="ignore rules")


async def test_truncated_result_needs_selection():
    class Limited(FakeEdgar):
        async def search(self, query, query_type):
            result = await super().search(query, query_type)
            result.truncated = True
            return result

    result = await IdentificationSkill(Limited([company(tickers=("AAPL",))])).execute(
        {"query": "Apple", "query_type": "name"}
    )
    assert result.status == "ambiguous"
    assert result.company is None


async def test_profile_cik_contradiction_is_error():
    class Contradictory(FakeEdgar):
        async def profile(self, cik):
            return company("42", "Other")

    result = await IdentificationSkill(Contradictory([company()])).execute({"query": "Apple", "query_type": "name"})
    assert result.status == "error"
    assert result.company is None


async def test_logs_do_not_contain_query_or_response(caplog):
    import logging

    caplog.set_level(logging.INFO)
    await IdentificationSkill(FakeEdgar([company(name="SECRET_TOOL_CONTENT")])).execute(
        {"query": "PRIVATE_QUERY", "query_type": "name"}
    )
    assert "SECRET_TOOL_CONTENT" not in caplog.text
    assert "PRIVATE_QUERY" not in caplog.text
    assert "correlation_id=" in caplog.text


def test_result_requires_valid_field_sources():
    from ai_agent_lab.credit.domain.models import IdentificationResult

    profile, source = company()
    profile.field_sources["legal_name"] = ["not-a-source"]
    with pytest.raises(ValueError):
        IdentificationResult(status="identified", query="Apple", query_type="name", company=profile, sources=[source])
