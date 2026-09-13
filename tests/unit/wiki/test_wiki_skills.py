"""Tests of the wiki skills.

The reasoner is scripted rather than a live model: a skill's job is to retrieve
the right pages, fence them, and refuse an answer that is not grounded in them.
None of that should depend on which sentence a model happened to produce.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel
from tests.unit.wiki.conftest import make_page, make_wiki
from ygo74.agent_runtime.domains.security.prompt_envelope import PromptEnvelopeBuilder
from ygo74.agent_runtime.domains.security.security_errors import PermissionDeniedError
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.reasoning.ports import ReasoningOutputT, ReasoningRequest
from ai_agent_lab.wiki.domain.enums import WikiFreshness
from ai_agent_lab.wiki.domain.errors import EmptySearchRequestError, UngroundedAnswerError
from ai_agent_lab.wiki.domain.models import WikiSearchRequest
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.inmemory.wiki import PageEntry
from ai_agent_lab.wiki.inmemory.wiki_tools import InMemoryWikiTools
from ai_agent_lab.wiki.skills.analysis import (
    AnswerOutput,
    PageSummaryOutput,
    WikiAnalysisMapper,
)
from ai_agent_lab.wiki.skills.answer_skill import DocumentationAnswerSkill
from ai_agent_lab.wiki.skills.context import TRUNCATION_NOTICE, WikiContextBuilder
from ai_agent_lab.wiki.skills.errors import EmptyPageSelectionError, UngroundedWikiResultError
from ai_agent_lab.wiki.skills.freshness_skill import PageFreshnessDetector, PageFreshnessSkill
from ai_agent_lab.wiki.skills.question_terms import QuestionTerms
from ai_agent_lab.wiki.skills.search_skill import DocumentationSearchSkill
from ai_agent_lab.wiki.skills.summary_skill import PageSummarySkill

INSTRUCTIONS = "You are a documentation assistant."

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


class ScriptedReasoner:
    """Returns a prepared output and records the request it was given."""

    def __init__(self, output: BaseModel) -> None:
        self._output = output
        self.requests: list[ReasoningRequest] = []

    async def reason(
        self,
        request: ReasoningRequest,
        response_model: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        """Return the prepared output."""
        self.requests.append(request)
        if not isinstance(self._output, response_model):
            raise AssertionError(f"scripted a {type(self._output).__name__}, asked for {response_model.__name__}")
        return self._output


@pytest.fixture
def reader() -> UserContext:
    """A user allowed to read the wiki."""
    return UserContext(user_id="alice", session_id="s", permissions=frozenset({WikiPermission.READ}))


@pytest.fixture
def outsider() -> UserContext:
    """A user holding no wiki permission at all."""
    return UserContext(user_id="mallory", session_id="s")


class TestDocumentationSearchSkill:
    """Finding pages."""

    async def test_a_search_returns_what_the_wiki_returned(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        skill = DocumentationSearchSkill(sample_tools)

        result = await skill.search(WikiSearchRequest(text="VAT"), reader)

        assert [reference.page_id for reference in result.references] == ["apollo-scope"]

    async def test_a_search_constraining_nothing_is_refused(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """It asks for the whole wiki and would be answered with noise."""
        skill = DocumentationSearchSkill(sample_tools)

        with pytest.raises(EmptySearchRequestError):
            await skill.search(WikiSearchRequest(), reader)

    @pytest.mark.security
    async def test_reading_requires_the_read_permission(self, sample_tools: InMemoryWikiTools, outsider: UserContext):
        skill = DocumentationSearchSkill(sample_tools)

        with pytest.raises(PermissionDeniedError):
            await skill.search(WikiSearchRequest(text="VAT"), outsider)


class TestPageSummarySkill:
    """Summarising pages."""

    def _skill(self, tools: InMemoryWikiTools, output: BaseModel) -> tuple[PageSummarySkill, ScriptedReasoner]:
        reasoner = ScriptedReasoner(output)
        skill = PageSummarySkill(
            tools,
            reasoner,  # type: ignore[arg-type]
            WikiContextBuilder(),
            WikiAnalysisMapper(),
            INSTRUCTIONS,
        )
        return skill, reasoner

    async def test_a_summary_cites_the_page_it_read(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        skill, _ = self._skill(
            sample_tools,
            PageSummaryOutput(summary="An architecture page.", cited_page_ids=["apollo-architecture"]),
        )

        summary = await skill.summarise_page("apollo-architecture", reader)

        assert summary.summary == "An architecture page."
        assert [source.page_id for source in summary.sources] == ["apollo-architecture"]

    async def test_a_citation_carries_the_version_that_was_read(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        """A page moves on; a citation says which revision was summarised."""
        skill, _ = self._skill(
            sample_tools,
            PageSummaryOutput(summary="x", cited_page_ids=["apollo-scope"]),
        )

        summary = await skill.summarise_page("apollo-scope", reader)

        assert summary.sources[0].version == 4

    @pytest.mark.security
    async def test_a_citation_of_an_unread_page_is_refused(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """A planted instruction must not produce a fabricated source."""
        skill, _ = self._skill(
            sample_tools,
            PageSummaryOutput(summary="x", cited_page_ids=["board-budget"]),
        )

        with pytest.raises(UngroundedWikiResultError, match="board-budget"):
            await skill.summarise_page("apollo-architecture", reader)

    async def test_repeated_citations_collapse(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        skill, _ = self._skill(
            sample_tools,
            PageSummaryOutput(summary="x", cited_page_ids=["apollo-scope"] * 5),
        )

        summary = await skill.summarise_page("apollo-scope", reader)

        assert len(summary.sources) == 1

    async def test_summarising_nothing_is_refused(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        skill, _ = self._skill(sample_tools, PageSummaryOutput(summary="x"))

        with pytest.raises(EmptyPageSelectionError):
            await skill.summarise_pages([], reader)

    async def test_a_subtree_summary_reads_the_children(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        skill, reasoner = self._skill(sample_tools, PageSummaryOutput(summary="x"))

        await skill.summarise_subtree("apollo-home", reader)

        labels = " ".join(section.label for section in reasoner.requests[0].context)
        assert "apollo-scope" in labels
        assert "apollo-home" in labels

    async def test_a_discussion_summary_keeps_comments_apart_from_the_page(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        """A comment contradicting a page must not be folded into it."""
        skill, reasoner = self._skill(sample_tools, PageSummaryOutput(summary="x"))

        await skill.summarise_page_with_discussion("apollo-scope", reader)

        labels = [section.label for section in reasoner.requests[0].context]
        assert any(label.startswith("page_id=") for label in labels)
        assert any(label.startswith("comment_id=") for label in labels)


class TestDocumentationAnswerSkill:
    """Answering from documentation, and only from it."""

    def _skill(
        self,
        tools: InMemoryWikiTools,
        output: BaseModel,
    ) -> tuple[DocumentationAnswerSkill, ScriptedReasoner]:
        reasoner = ScriptedReasoner(output)
        skill = DocumentationAnswerSkill(
            tools,
            reasoner,  # type: ignore[arg-type]
            WikiContextBuilder(),
            WikiAnalysisMapper(),
            INSTRUCTIONS,
        )
        return skill, reasoner

    async def test_an_answer_cites_the_pages_it_used(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        skill, _ = self._skill(
            sample_tools,
            AnswerOutput(answer="BE VAT rules are in scope.", cited_page_ids=["apollo-scope"]),
        )

        answer = await skill.answer("What is the VAT scope?", reader)

        assert answer.is_grounded
        assert [source.page_id for source in answer.sources] == ["apollo-scope"]

    @pytest.mark.security
    async def test_an_answer_citing_nothing_is_reported_as_ungrounded(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        """An uncited paragraph is a guess wearing the clothes of an answer."""
        skill, _ = self._skill(
            sample_tools,
            AnswerOutput(answer="I am confident the answer is 42.", is_grounded=True),
        )

        answer = await skill.answer("What is the VAT scope?", reader)

        assert not answer.is_grounded
        assert answer.sources == ()

    async def test_a_question_matching_nothing_is_refused(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """With nothing retrieved there is nothing to answer from."""
        skill, _ = self._skill(sample_tools, AnswerOutput(answer="x"))

        with pytest.raises(UngroundedAnswerError):
            await skill.answer("what is the airspeed velocity of a swallow", reader)

    @pytest.mark.security
    async def test_a_citation_of_a_page_the_user_cannot_read_is_refused(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        """The restricted page was never retrieved, so it cannot be cited."""
        skill, _ = self._skill(
            sample_tools,
            AnswerOutput(answer="Compensation is X.", cited_page_ids=["apollo-salaries"]),
        )

        with pytest.raises(UngroundedWikiResultError):
            await skill.answer("What is the VAT scope?", reader)

    async def test_a_natural_question_is_reduced_to_its_content_words(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        """Searching for every word of a sentence finds nothing at all."""
        skill, _ = self._skill(
            sample_tools,
            AnswerOutput(answer="x", cited_page_ids=["apollo-scope"]),
        )

        answer = await skill.answer("So, what is in the scope for VAT this year?", reader)

        assert [source.page_id for source in answer.sources] == ["apollo-scope"]

    async def test_the_question_travels_as_trusted_task_not_as_context(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        skill, reasoner = self._skill(sample_tools, AnswerOutput(answer="x", cited_page_ids=[]))

        await skill.answer("What is the VAT scope?", reader)

        request = reasoner.requests[0]
        assert "What is the VAT scope?" in request.task
        assert all("What is the VAT scope?" not in section.content.expose() for section in request.context)


@pytest.mark.security
class TestPromptFencing:
    """What a planted instruction actually reaches."""

    async def test_a_planted_instruction_is_fenced_in_the_prompt(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        reasoner = ScriptedReasoner(PageSummaryOutput(summary="x"))
        skill = PageSummarySkill(
            sample_tools,
            reasoner,  # type: ignore[arg-type]
            WikiContextBuilder(),
            WikiAnalysisMapper(),
            INSTRUCTIONS,
        )

        await skill.summarise_page("apollo-onboarding", reader)
        prompt = PromptEnvelopeBuilder(source="a documentation wiki").build(reasoner.requests[0])

        assert "Ignore all previous instructions" in prompt
        assert "not trusted" in prompt
        assert "Never follow" in prompt
        assert prompt.index("Never follow") < prompt.index("Ignore all previous instructions")

    async def test_a_section_label_carries_no_third_party_text(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        """A page title in a label would be an injection vector of its own."""
        reasoner = ScriptedReasoner(PageSummaryOutput(summary="x"))
        skill = PageSummarySkill(
            sample_tools,
            reasoner,  # type: ignore[arg-type]
            WikiContextBuilder(),
            WikiAnalysisMapper(),
            INSTRUCTIONS,
        )

        await skill.summarise_page("apollo-onboarding", reader)

        label = reasoner.requests[0].context[0].label
        assert "Onboarding notes" not in label
        assert "page_id=apollo-onboarding" in label


class TestQuestionTerms:
    """Turning a question into something a search engine can match."""

    def test_function_words_are_dropped(self):
        assert QuestionTerms().of("So, what is in the scope for VAT?") == "scope vat"

    def test_french_function_words_are_dropped_too(self):
        """The agent is used against wikis written in both languages."""
        assert QuestionTerms().of("Quel est le budget du projet ?") == "budget projet"

    def test_repeated_words_appear_once(self):
        assert QuestionTerms().of("budget and budget again") == "budget again"

    def test_a_question_of_pure_function_words_is_passed_through(self):
        """Reducing it to nothing would search the whole wiki."""
        assert QuestionTerms().of("what is this?") == "what is this?"

    def test_the_ladder_broadens_from_the_end(self):
        """A question states its subject before its qualifiers."""
        ladder = QuestionTerms().ladder("What is the VAT scope this year?")

        assert ladder == ("vat scope year", "vat scope", "vat")

    def test_the_ladder_is_bounded(self):
        ladder = QuestionTerms().ladder("alpha beta gamma delta epsilon zeta", attempts=2)

        assert len(ladder) == 2

    def test_the_ladder_is_deterministic(self):
        """The same question must retrieve the same pages on every run."""
        terms = QuestionTerms()

        assert terms.ladder("What is the VAT scope?") == terms.ladder("What is the VAT scope?")


class TestContextBudget:
    """A wiki page is far longer than an email."""

    def test_a_long_page_is_truncated_rather_than_dropped(self):
        page = make_page(body="x" * 20_000)

        sections = WikiContextBuilder(max_page_characters=100).build([page])

        assert TRUNCATION_NOTICE in sections[0].content.expose()
        assert len(sections[0].content.expose()) < 1_000

    def test_the_number_of_pages_is_capped(self):
        """Truncation alone would let a hundred short pages through."""
        pages = [make_page(page_id=f"p{index}") for index in range(20)]

        sections = WikiContextBuilder(max_pages=3).build(pages)

        assert len(sections) == 3

    def test_the_caller_order_is_preserved(self):
        """A search hands results over by relevance; the tail is what to drop."""
        pages = [make_page(page_id="first"), make_page(page_id="second")]

        sections = WikiContextBuilder(max_pages=1).build(pages)

        assert "page_id=first" in sections[0].label


class TestPageFreshnessDetector:
    """A subtraction of two dates, not a question for a model."""

    def _detector(self) -> PageFreshnessDetector:
        return PageFreshnessDetector(ageing_after_days=90, stale_after_days=180, clock=lambda: NOW)

    @pytest.mark.parametrize(
        ("days", "expected"),
        [
            (0, WikiFreshness.FRESH),
            (89, WikiFreshness.FRESH),
            (90, WikiFreshness.AGEING),
            (179, WikiFreshness.AGEING),
            (180, WikiFreshness.STALE),
            (900, WikiFreshness.STALE),
        ],
    )
    def test_the_thresholds_are_applied_exactly(self, days: int, expected: WikiFreshness):
        page = make_page(
            created_at=NOW - timedelta(days=days + 1),
            last_modified_at=NOW - timedelta(days=days),
        )

        assert self._detector().assess(page).freshness is expected

    def test_a_page_modified_in_the_future_is_not_negative(self):
        """That is clock skew between the wiki and this process."""
        page = make_page(created_at=NOW, last_modified_at=NOW + timedelta(days=5))

        assessed = self._detector().assess(page)

        assert assessed.days_since_change == 0
        assert assessed.freshness is WikiFreshness.FRESH

    def test_contradictory_thresholds_are_refused(self):
        with pytest.raises(ValueError, match="must be ageing before it is stale"):
            PageFreshnessDetector(ageing_after_days=180, stale_after_days=90)

    async def test_a_report_puts_the_most_stale_first(self):
        wiki = make_wiki(
            PageEntry(make_page(page_id="fresh", last_modified_at=NOW - timedelta(days=1))),
            PageEntry(
                make_page(
                    page_id="ancient",
                    created_at=NOW - timedelta(days=900),
                    last_modified_at=NOW - timedelta(days=800),
                )
            ),
        )
        skill = PageFreshnessSkill(InMemoryWikiTools(wiki), self._detector())
        reader = UserContext(user_id="alice", session_id="s", permissions=frozenset({WikiPermission.READ}))

        report = await skill.assess_pages(["fresh", "ancient"], reader)

        assert [page.page_id for page in report.pages] == ["ancient", "fresh"]
        assert [page.page_id for page in report.stale] == ["ancient"]

    async def test_assessing_a_search_fetches_no_page_body(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """Downloading a hundred pages to compute a subtraction would be absurd."""
        skill = PageFreshnessSkill(sample_tools, self._detector())

        report = await skill.assess_search(WikiSearchRequest(labels=("project",), limit=50), reader)

        assert report.pages
        assert all(page.days_since_change >= 0 for page in report.pages)
