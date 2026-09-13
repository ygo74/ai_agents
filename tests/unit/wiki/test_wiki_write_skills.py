"""Tests of the wiki capabilities that change something.

Three things are pinned here, and they are independent of each other.

The *gate* is pinned: no write runs without the permission and, where the policy
demands it, without a decision that answers the very request the user was shown.
The gate is re-checked inside the skill, so invoking it directly - from a script,
from a test, from another framework - cannot bypass what the framework enforces.

The *audit trail* is pinned: every attempt leaves a record, including the ones
that were blocked, declined or failed, and no record ever carries page text.

The *draft* is pinned: writing publishes the stored draft, not arguments a model
supplied afterwards, and a reference issued to one person is worthless to another.
"""

from __future__ import annotations

import pytest
from tests.unit.wiki.conftest import make_page, make_wiki
from ygo74.agent_runtime.domains.humanapproval.approval_errors import (
    ConfirmationMismatchError,
    ConfirmationRejectedError,
    ConfirmationRequiredError,
)
from ygo74.agent_runtime.domains.humanapproval.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationDecision,
    ConfirmationGate,
    ConfirmationPreferences,
    InMemoryConfirmationPreferenceStore,
)
from ygo74.agent_runtime.domains.security.audit import AuditOutcome, InMemoryAuditTrail
from ygo74.agent_runtime.domains.security.security_errors import PermissionDeniedError
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.wiki.catalog import WikiToolCatalog, WikiToolName
from ai_agent_lab.wiki.domain.errors import WikiDraftNotFoundError
from ai_agent_lab.wiki.domain.models import WikiPageDraft
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.inmemory.draft_store import InMemoryWikiDraftStore
from ai_agent_lab.wiki.inmemory.wiki import PageEntry
from ai_agent_lab.wiki.inmemory.wiki_tools import InMemoryWikiTools
from ai_agent_lab.wiki.security_floor import WikiSecurityFloor
from ai_agent_lab.wiki.skills.authoring_skill import PageAuthoringSkill
from ai_agent_lab.wiki.skills.comment_skill import PageCommentSkill
from ai_agent_lab.wiki.skills.errors import EmptyCommentError, EmptyPageContentError
from ai_agent_lab.wiki.skills.gating import GatedWikiOperationRunner
from ai_agent_lab.wiki.wiki_errors import WikiConcurrentEditError, WikiNotFoundError

CONFIDENTIAL_BODY = "The compensation review concluded on the sixth of March."


def policy_with(**preferences: bool) -> ConfiguredConfirmationPolicy:
    """Build the policy of a deployment, under the real security floor."""
    return ConfiguredConfirmationPolicy(
        InMemoryConfirmationPreferenceStore(
            {
                "diana": ConfirmationPreferences(
                    auto_approved_tools=frozenset(
                        name for name, approved in preferences.items() if approved
                    ),
                    always_confirm_tools=frozenset(
                        name for name, approved in preferences.items() if not approved
                    ),
                )
            }
        ),
        WikiSecurityFloor().build(),
    )


@pytest.fixture
def audit() -> InMemoryAuditTrail:
    """A trail the assertions can read back."""
    return InMemoryAuditTrail()


@pytest.fixture
def tools() -> InMemoryWikiTools:
    """A small wiki holding one page."""
    return InMemoryWikiTools(make_wiki(PageEntry(make_page(page_id="p1", version=2))))


def build_runner(
    audit: InMemoryAuditTrail,
    policy: ConfiguredConfirmationPolicy | None = None,
) -> GatedWikiOperationRunner:
    """Build the gated runner over the coded catalogue."""
    chosen = policy or policy_with()
    return GatedWikiOperationRunner(WikiToolCatalog(), chosen, ConfirmationGate(chosen), audit)


@pytest.fixture
def authoring(tools: InMemoryWikiTools, audit: InMemoryAuditTrail) -> PageAuthoringSkill:
    """The authoring skill over the small wiki."""
    return PageAuthoringSkill(tools, tools, build_runner(audit))


@pytest.fixture
def commenting(tools: InMemoryWikiTools, audit: InMemoryAuditTrail) -> PageCommentSkill:
    """The comment skill over the small wiki."""
    return PageCommentSkill(tools, build_runner(audit))


def draft_for_new_page(body: str = "A new page.") -> WikiPageDraft:
    """A draft that would create a page."""
    return WikiPageDraft(
        space_key="APOLLO",
        title=untrusted("Runbook", UntrustedOrigin.WIKI_PAGE_TITLE),
        body=untrusted(body, UntrustedOrigin.WIKI_PAGE_BODY),
    )


def draft_for_revision(body: str = "A revised page.", *, version: int | None = 2) -> WikiPageDraft:
    """A draft that would replace the body of ``p1``."""
    return WikiPageDraft(
        space_key="APOLLO",
        title=untrusted("Charter", UntrustedOrigin.WIKI_PAGE_TITLE),
        body=untrusted(body, UntrustedOrigin.WIKI_PAGE_BODY),
        page_id="p1",
        expected_version=version,
    )


def approval(request, *, approved: bool = True, by: str = "diana") -> ConfirmationDecision:
    """Build the decision answering a request."""
    return ConfirmationDecision(request_id=request.request_id, approved=approved, decided_by=by)


class TestAuthoringUnderApproval:
    """A write runs when, and only when, it was properly authorised."""

    async def test_an_approved_creation_stores_the_page(self, authoring, author, tools):
        draft = draft_for_new_page()
        request = authoring.build_create_confirmation_request(draft, author)

        page = await authoring.create_page(
            draft, author, request=request, decision=approval(request)
        )

        assert page.body.expose() == "A new page."
        assert (await tools.get_page(page.page_id, author)).title.expose() == "Runbook"

    async def test_an_approved_revision_bumps_the_version(self, authoring, author, tools):
        draft = draft_for_revision()
        request = authoring.build_update_confirmation_request(draft, author)

        await authoring.update_page(draft, author, request=request, decision=approval(request))

        page = await tools.get_page("p1", author)
        assert page.body.expose() == "A revised page."
        assert page.version == 3

    async def test_an_approved_deletion_removes_the_page(self, authoring, author, tools):
        request = await authoring.build_delete_confirmation_request("p1", author)

        await authoring.delete_page("p1", author, request=request, decision=approval(request))

        with pytest.raises(WikiNotFoundError):
            await tools.get_page("p1", author)


@pytest.mark.security
class TestAuthoringRefusals:
    """Everything that must stop a write."""

    async def test_a_gated_write_without_a_decision_is_refused(self, authoring, author, tools):
        with pytest.raises(ConfirmationRequiredError):
            await authoring.update_page(draft_for_revision(), author)

        assert (await tools.get_page("p1", author)).version == 2

    async def test_a_declined_write_is_refused(self, authoring, author, tools):
        draft = draft_for_revision()
        request = authoring.build_update_confirmation_request(draft, author)

        with pytest.raises(ConfirmationRejectedError):
            await authoring.update_page(
                draft, author, request=request, decision=approval(request, approved=False)
            )

        assert (await tools.get_page("p1", author)).version == 2

    async def test_a_decision_answering_another_request_is_refused(self, authoring, author):
        draft = draft_for_revision()
        request = authoring.build_update_confirmation_request(draft, author)
        other = authoring.build_update_confirmation_request(draft, author)

        with pytest.raises(ConfirmationMismatchError):
            await authoring.update_page(
                draft, author, request=request, decision=approval(other)
            )

    async def test_an_approval_granted_by_somebody_else_is_refused(self, authoring, author):
        draft = draft_for_revision()
        request = authoring.build_update_confirmation_request(draft, author)

        with pytest.raises(ConfirmationMismatchError):
            await authoring.update_page(
                draft, author, request=request, decision=approval(request, by="alice")
            )

    async def test_a_reader_may_not_author(self, authoring, reader):
        with pytest.raises(PermissionDeniedError):
            await authoring.create_page(draft_for_new_page(), reader)

    async def test_authoring_is_not_managing(self, authoring, tools):
        """Writing pages does not carry the right to delete them."""
        writer = UserContext(
            user_id="diana",
            session_id="s",
            permissions=frozenset({WikiPermission.READ, WikiPermission.AUTHOR}),
        )

        with pytest.raises(PermissionDeniedError):
            await authoring.delete_page("p1", writer)

        assert await tools.get_page("p1", writer) is not None

    async def test_an_empty_body_is_refused(self, authoring, author, tools):
        with pytest.raises(EmptyPageContentError):
            await authoring.create_page(draft_for_new_page("   "), author)

        assert (await tools.get_page("p1", author)).version == 2

    async def test_a_page_edited_in_the_meantime_is_not_overwritten(self, authoring, author, tools):
        """The version the draft was composed against no longer exists."""
        draft = draft_for_revision(version=1)
        request = authoring.build_update_confirmation_request(draft, author)

        with pytest.raises(WikiConcurrentEditError):
            await authoring.update_page(draft, author, request=request, decision=approval(request))

        assert (await tools.get_page("p1", author)).version == 2


@pytest.mark.security
class TestSecurityFloor:
    """What a delivered configuration may not soften."""

    def test_a_preference_cannot_ungate_a_replacement(self, tools, audit, author):
        """update_page is pinned by the floor, whatever a user prefers."""
        skill = PageAuthoringSkill(tools, tools, build_runner(audit, policy_with(update_page=True)))

        assert skill.requires_confirmation(WikiToolName.UPDATE_PAGE, author)

    def test_a_preference_cannot_ungate_a_deletion(self, tools, audit, author):
        skill = PageAuthoringSkill(tools, tools, build_runner(audit, policy_with(delete_page=True)))

        assert skill.requires_confirmation(WikiToolName.DELETE_PAGE, author)

    def test_a_comment_stays_configurable(self, tools, audit, author):
        """The floor holds the line at what damages existing content."""
        skill = PageCommentSkill(tools, build_runner(audit, policy_with(add_comment=True)))

        assert not skill.requires_confirmation(author)


class TestAuditTrail:
    """Every attempt leaves a record, and none of them carries page text."""

    async def test_an_executed_write_is_recorded(self, authoring, author, audit):
        draft = draft_for_revision()
        request = authoring.build_update_confirmation_request(draft, author)

        await authoring.update_page(draft, author, request=request, decision=approval(request))

        entry = audit.records_for(WikiToolName.UPDATE_PAGE.value)[0]
        assert entry.outcome is AuditOutcome.EXECUTED
        assert entry.target_id == "p1"
        assert entry.confirmation_request_id == request.request_id

    async def test_a_declined_write_is_recorded_as_declined(self, authoring, author, audit):
        draft = draft_for_revision()
        request = authoring.build_update_confirmation_request(draft, author)

        with pytest.raises(ConfirmationRejectedError):
            await authoring.update_page(
                draft, author, request=request, decision=approval(request, approved=False)
            )

        assert audit.records_for(WikiToolName.UPDATE_PAGE.value)[0].outcome is AuditOutcome.DECLINED

    async def test_a_write_without_permission_is_recorded_as_blocked(self, authoring, reader, audit):
        with pytest.raises(PermissionDeniedError):
            await authoring.create_page(draft_for_new_page(), reader)

        assert audit.records_for(WikiToolName.CREATE_PAGE.value)[0].outcome is AuditOutcome.BLOCKED

    async def test_a_failed_write_is_recorded_as_failed(self, authoring, author, audit):
        draft = draft_for_revision(version=1)
        request = authoring.build_update_confirmation_request(draft, author)

        with pytest.raises(WikiConcurrentEditError):
            await authoring.update_page(draft, author, request=request, decision=approval(request))

        entry = audit.records_for(WikiToolName.UPDATE_PAGE.value)[0]
        assert entry.outcome is AuditOutcome.FAILED
        assert entry.error_type == "WikiConcurrentEditError"

    @pytest.mark.security
    async def test_the_trail_never_holds_page_content(self, authoring, author, audit):
        """A trail is read by people who may not read the page it names."""
        draft = draft_for_revision(CONFIDENTIAL_BODY)
        request = authoring.build_update_confirmation_request(draft, author)

        await authoring.update_page(draft, author, request=request, decision=approval(request))

        recorded = audit.records_for(WikiToolName.UPDATE_PAGE.value)[0].model_dump_json()
        assert CONFIDENTIAL_BODY not in recorded
        assert "Charter" not in recorded


class TestConfirmationRequests:
    """What the person deciding is actually shown."""

    def test_a_replacement_shows_the_body_and_the_version(self, authoring, author):
        request = authoring.build_update_confirmation_request(draft_for_revision(), author)

        shown = {detail.label: detail.value for detail in request.details}
        assert shown["New body"] == "A revised page."
        assert shown["Page"] == "p1"
        assert shown["Replaces version"] == "2"

    def test_a_creation_shows_the_space_and_the_title(self, authoring, author):
        request = authoring.build_create_confirmation_request(draft_for_new_page(), author)

        shown = {detail.label: detail.value for detail in request.details}
        assert shown["Space"] == "APOLLO"
        assert shown["Title"] == "Runbook"

    async def test_a_deletion_names_the_page_it_removes(self, authoring, author):
        request = await authoring.build_delete_confirmation_request("p1", author)

        shown = {detail.label: detail.value for detail in request.details}
        assert shown["Page"] == "p1"
        assert shown["Title"] == "Charter"

    async def test_a_deletion_of_an_unreadable_page_is_still_describable(self, authoring, author):
        """A wiki permission problem must not become an unexplained refusal."""
        request = await authoring.build_delete_confirmation_request("ghost", author)

        assert request.target == "ghost"

    def test_a_long_body_is_truncated_for_the_prompt(self, authoring, author):
        request = authoring.build_create_confirmation_request(
            draft_for_new_page("x" * 5000), author
        )

        shown = {detail.label: detail.value for detail in request.details}
        assert shown["Body"].endswith("[...]")
        assert len(shown["Body"]) < 2000

    @pytest.mark.security
    def test_the_target_identifies_the_operation(self, authoring, author):
        """The presenter and the capability must name the same thing."""
        request = authoring.build_update_confirmation_request(
            draft_for_revision(), author, target="wiki-draft-1"
        )

        assert request.key.tool_name == WikiToolName.UPDATE_PAGE.value
        assert request.key.target == "wiki-draft-1"


class TestComments:
    """Posting a comment, the mildest write of the four."""

    async def test_an_approved_comment_is_stored(self, commenting, author, tools):
        request = commenting.build_confirmation_request("p1", "A remark.", author)

        comment = await commenting.add_comment(
            "p1", "A remark.", author, request=request, decision=approval(request)
        )

        assert comment.body.expose() == "A remark."
        assert (await tools.get_comments("p1", author))[0].comment_id == comment.comment_id

    @pytest.mark.security
    async def test_a_comment_needs_the_comment_permission(self, commenting, tools):
        reader_only = UserContext(
            user_id="diana", session_id="s", permissions=frozenset({WikiPermission.READ})
        )

        with pytest.raises(PermissionDeniedError):
            await commenting.add_comment("p1", "A remark.", reader_only)

        assert await tools.get_comments("p1", reader_only) == ()

    async def test_an_empty_comment_is_refused(self, commenting, author):
        with pytest.raises(EmptyCommentError):
            await commenting.add_comment("p1", "   ", author)

    def test_the_comment_is_shown_before_it_is_posted(self, commenting, author):
        request = commenting.build_confirmation_request("p1", "A remark.", author)

        shown = {detail.label: detail.value for detail in request.details}
        assert shown["Comment"] == "A remark."
        assert shown["Page"] == "p1"


@pytest.mark.security
class TestDraftStore:
    """A reference is a capability, so it is scoped to the person issued it."""

    def test_a_draft_is_returned_to_its_author(self, author):
        store = InMemoryWikiDraftStore()
        reference = store.put(draft_for_new_page(), author)

        assert store.get(reference, author).body.expose() == "A new page."

    def test_a_reference_is_worthless_to_another_person(self, author, reader):
        store = InMemoryWikiDraftStore()
        reference = store.put(draft_for_new_page(CONFIDENTIAL_BODY), author)

        with pytest.raises(WikiDraftNotFoundError):
            store.get(reference, reader)

    def test_an_unknown_reference_is_refused(self, author):
        with pytest.raises(WikiDraftNotFoundError):
            InMemoryWikiDraftStore().get("wiki-draft-nope", author)

    def test_the_refusal_never_reveals_the_content(self, author, reader):
        """Telling a caller a reference exists would leak what somebody drafts."""
        store = InMemoryWikiDraftStore()
        reference = store.put(draft_for_new_page(CONFIDENTIAL_BODY), author)

        with pytest.raises(WikiDraftNotFoundError) as raised:
            store.get(reference, reader)

        assert CONFIDENTIAL_BODY not in str(raised.value)


class TestDraftModel:
    """A draft must name somewhere to go."""

    def test_a_draft_with_no_destination_is_refused(self):
        with pytest.raises(ValueError, match="either the page it replaces or the space"):
            WikiPageDraft(body=untrusted("x", UntrustedOrigin.WIKI_PAGE_BODY))

    def test_a_new_page_needs_a_title(self):
        with pytest.raises(ValueError, match="must carry a title"):
            WikiPageDraft(
                space_key="APOLLO",
                body=untrusted("x", UntrustedOrigin.WIKI_PAGE_BODY),
            )

    def test_a_revision_needs_no_title(self):
        draft = WikiPageDraft(
            page_id="p1",
            body=untrusted("x", UntrustedOrigin.WIKI_PAGE_BODY),
        )

        assert draft.replaces_a_page
