"""Tests of the in-memory wiki tools.

They run against the delivered dataset, which is deliberately untidy: pages
contradict each other, one is archived, one is restricted and one carries a
prompt injection.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.unit.wiki.conftest import make_page, make_space, make_wiki

from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.wiki.domain.enums import WikiPageStatus, WikiSortOrder
from ai_agent_lab.wiki.domain.models import WikiSearchRequest
from ai_agent_lab.wiki.inmemory.wiki import PageEntry, SpaceEntry
from ai_agent_lab.wiki.inmemory.wiki_tools import InMemoryWikiTools
from ai_agent_lab.wiki.tools_port import WikiTools
from ai_agent_lab.wiki.wiki_errors import (
    WikiAccessDeniedError,
    WikiConcurrentEditError,
    WikiNotFoundError,
)


class TestContract:
    """The in-memory implementation is a full implementation."""

    def test_it_satisfies_the_whole_tool_surface(self, sample_tools: InMemoryWikiTools):
        assert isinstance(sample_tools, WikiTools)


class TestSearch:
    """What a search returns, and what it deliberately does not."""

    async def test_search_returns_references_never_bodies(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """A broad query must not pull whole pages into the conversation."""
        result = await sample_tools.search(WikiSearchRequest(text="apollo"), reader)

        assert result.references
        assert all(not hasattr(reference, "body") for reference in result.references)

    async def test_every_free_text_term_must_appear(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        both = await sample_tools.search(WikiSearchRequest(text="VAT reconciliation"), reader)
        neither = await sample_tools.search(WikiSearchRequest(text="VAT kubernetes"), reader)

        assert [r.page_id for r in both.references] == ["apollo-scope"]
        assert not neither.references

    async def test_archived_pages_are_excluded_by_default(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        current = await sample_tools.search(WikiSearchRequest(text="phase"), reader)
        archived = await sample_tools.search(
            WikiSearchRequest(text="phase", statuses=(WikiPageStatus.ARCHIVED,)), reader
        )

        assert not current.references
        assert [r.page_id for r in archived.references] == ["apollo-old-plan"]

    async def test_a_search_can_be_restricted_to_a_space(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        result = await sample_tools.search(WikiSearchRequest(space_keys=("ENG",), text="python"), reader)

        assert [r.page_id for r in result.references] == ["eng-python"]

    async def test_labels_must_all_be_carried(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        both = await sample_tools.search(WikiSearchRequest(labels=("project", "scope")), reader)
        missing = await sample_tools.search(WikiSearchRequest(labels=("project", "budget")), reader)

        assert [r.page_id for r in both.references] == ["apollo-scope"]
        assert not missing.references

    async def test_a_truncated_search_says_so(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """ "Here are the first two" must be distinguishable from "there are two"."""
        result = await sample_tools.search(WikiSearchRequest(labels=("project",), limit=2), reader)

        assert len(result.references) == 2
        assert result.total_count > 2
        assert result.truncated

    async def test_results_can_be_ordered_by_title(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        result = await sample_tools.search(
            WikiSearchRequest(labels=("project",), sort_order=WikiSortOrder.TITLE, limit=50), reader
        )

        titles = [reference.title.expose() for reference in result.references]
        assert titles == sorted(titles, key=str.casefold)

    async def test_a_date_window_narrows_the_result(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        result = await sample_tools.search(
            WikiSearchRequest(
                labels=("project",),
                modified_after=datetime(2026, 9, 1, tzinfo=UTC),
                limit=50,
            ),
            reader,
        )

        assert [r.page_id for r in result.references] == ["apollo-scope"]


class TestReads:
    """Retrieval of a single page and of what hangs off it."""

    async def test_a_page_is_returned_with_its_body(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        page = await sample_tools.get_page("apollo-architecture", reader)

        assert "PostgreSQL 16" in page.body.expose()

    async def test_children_are_one_level_deep(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        tree = await sample_tools.get_children("apollo-home", reader)

        assert tree.parent_id == "apollo-home"
        assert "apollo-scope" in {child.page_id for child in tree.children}

    async def test_history_runs_from_newest_to_oldest(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        history = await sample_tools.get_history("apollo-scope", reader)

        assert [version.version for version in history.versions] == [4, 3, 2, 1]
        assert history.current.version == 4

    async def test_comments_are_returned_oldest_first(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        comments = await sample_tools.get_comments("apollo-scope", reader)

        assert [comment.comment_id for comment in comments] == ["c-scope-1"]

    async def test_an_unknown_page_is_reported_as_missing(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        with pytest.raises(WikiNotFoundError):
            await sample_tools.get_page("no-such-page", reader)


class TestWrites:
    """State-changing operations."""

    async def test_creating_a_page_stores_it_with_a_history(self, author: UserContext):
        tools = InMemoryWikiTools(make_wiki())

        created = await tools.create_page("APOLLO", "Runbook", "How to deploy.", author)
        history = await tools.get_history(created.page_id, author)

        assert created.version == 1
        assert (await tools.get_page(created.page_id, author)).title.expose() == "Runbook"
        assert [entry.version for entry in history.versions] == [1]

    async def test_creating_a_page_in_an_unknown_space_is_refused(self, author: UserContext):
        tools = InMemoryWikiTools(make_wiki())

        with pytest.raises(WikiNotFoundError):
            await tools.create_page("NOPE", "Runbook", "body", author)

    async def test_updating_a_page_raises_its_version_and_extends_the_history(self, author: UserContext):
        tools = InMemoryWikiTools(make_wiki(PageEntry(make_page(page_id="p1", version=1))))

        updated = await tools.update_page("p1", "New body.", author)
        history = await tools.get_history("p1", author)

        assert updated.version == 2
        assert updated.body.expose() == "New body."
        assert [entry.version for entry in history.versions] == [2, 1]

    async def test_a_stale_write_is_refused_rather_than_silently_applied(self, author: UserContext):
        """An agent must not discard the edit a colleague made in between."""
        tools = InMemoryWikiTools(make_wiki(PageEntry(make_page(page_id="p1", version=4))))

        with pytest.raises(WikiConcurrentEditError) as failure:
            await tools.update_page("p1", "New body.", author, expected_version=3)

        assert failure.value.actual_version == 4
        assert (await tools.get_page("p1", author)).version == 4

    async def test_deleting_a_page_removes_it(self, author: UserContext):
        tools = InMemoryWikiTools(make_wiki(PageEntry(make_page(page_id="p1"))))

        await tools.delete_page("p1", author)

        with pytest.raises(WikiNotFoundError):
            await tools.get_page("p1", author)

    async def test_a_comment_is_attached_without_touching_the_body(self, author: UserContext):
        tools = InMemoryWikiTools(make_wiki(PageEntry(make_page(page_id="p1", body="Original."))))

        await tools.add_comment("p1", "A remark.", author)

        assert (await tools.get_page("p1", author)).body.expose() == "Original."
        assert [c.body.expose() for c in await tools.get_comments("p1", author)] == ["A remark."]

    async def test_replying_to_an_unknown_comment_is_refused(self, author: UserContext):
        tools = InMemoryWikiTools(make_wiki(PageEntry(make_page(page_id="p1"))))

        with pytest.raises(WikiNotFoundError):
            await tools.add_comment("p1", "A reply.", author, parent_comment_id="ghost")


@pytest.mark.security
class TestAuthorisation:
    """The wiki restricts pages and spaces, and so does this implementation."""

    async def test_a_restricted_page_is_refused_not_hidden(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """Reporting it as missing would tell users documentation does not exist."""
        with pytest.raises(WikiAccessDeniedError):
            await sample_tools.get_page("apollo-salaries", reader)

    async def test_the_owner_of_the_restriction_still_reads_it(
        self, sample_tools: InMemoryWikiTools, author: UserContext
    ):
        page = await sample_tools.get_page("apollo-salaries", author)

        assert page.page_id == "apollo-salaries"

    async def test_a_restricted_page_never_surfaces_in_a_search(
        self, sample_tools: InMemoryWikiTools, reader: UserContext
    ):
        """A search must not leak through an excerpt what a read would refuse."""
        result = await sample_tools.search(WikiSearchRequest(text="compensation"), reader)

        assert not result.references

    async def test_an_unreadable_space_is_absent_from_the_listing(
        self, sample_tools: InMemoryWikiTools, reader: UserContext, author: UserContext
    ):
        assert "BOARD" not in {space.key for space in await sample_tools.list_spaces(reader)}
        assert "BOARD" in {space.key for space in await sample_tools.list_spaces(author)}

    async def test_pages_of_an_unreadable_space_never_surface(
        self, sample_tools: InMemoryWikiTools, reader: UserContext, author: UserContext
    ):
        hidden = await sample_tools.search(WikiSearchRequest(text="over budget"), reader)
        visible = await sample_tools.search(WikiSearchRequest(text="over budget"), author)

        assert not hidden.references
        assert [r.page_id for r in visible.references] == ["board-budget"]

    async def test_children_of_a_restricted_page_are_not_enumerated(self, reader: UserContext):
        """Its shape leaks even when its content does not."""
        wiki = make_wiki(
            PageEntry(make_page(page_id="secret"), restricted_to=("diana",)),
            PageEntry(make_page(page_id="child", parent_id="secret")),
        )
        tools = InMemoryWikiTools(wiki)

        with pytest.raises(WikiAccessDeniedError):
            await tools.get_children("secret", reader)

    async def test_a_restricted_child_is_omitted_from_a_readable_parent(self, reader: UserContext):
        wiki = make_wiki(
            PageEntry(make_page(page_id="parent")),
            PageEntry(make_page(page_id="open", parent_id="parent")),
            PageEntry(make_page(page_id="closed", parent_id="parent"), restricted_to=("diana",)),
        )
        tools = InMemoryWikiTools(wiki)

        tree = await tools.get_children("parent", reader)

        assert {child.page_id for child in tree.children} == {"open"}

    async def test_a_space_restriction_outranks_an_open_page(self, reader: UserContext):
        """A page with no restriction of its own is still inside its space."""
        wiki = make_wiki(
            PageEntry(make_page(page_id="p1", space_key="BOARD")),
            spaces=(SpaceEntry(make_space("BOARD", "Board"), readable_by=("diana",)),),
        )
        tools = InMemoryWikiTools(wiki)

        with pytest.raises(WikiAccessDeniedError):
            await tools.get_page("p1", reader)


@pytest.mark.security
class TestUntrustedContent:
    """Everything the dataset carries crosses the boundary wrapped."""

    async def test_a_planted_instruction_arrives_as_data(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        page = await sample_tools.get_page("apollo-onboarding", reader)

        assert "Ignore all previous instructions" in page.body.expose()
        assert "Ignore all previous instructions" not in repr(page)

    async def test_search_excerpts_are_wrapped_too(self, sample_tools: InMemoryWikiTools, reader: UserContext):
        """An excerpt is a fragment of the page and is no more trusted than it."""
        result = await sample_tools.search(WikiSearchRequest(title_contains="Onboarding"), reader)

        excerpt = result.references[0].excerpt
        assert excerpt is not None
        assert "Ignore all previous instructions" not in repr(excerpt)
