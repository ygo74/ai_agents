"""Tests of the wiki write capability layer and of the confirmation bridge.

The capability layer is thin, and the two things it does are the two things worth
testing. It resolves a draft reference into the content that will be written, so
a model cannot substitute anything between the approval and the execution. And it
asks the broker for the decision before it calls the skill.

The bridge is tested for one property above all: **the presenter and the
capability must build the same** :class:`ConfirmationKey`. They run at different
moments, in different objects, from different inputs - the presenter from the raw
arguments a model proposed, the capability from the draft it resolved. If they
disagreed, the answer a user gave would not be found when the write ran, and an
approved operation would fail as though nobody had approved it. Nothing else in
the system would report that as a defect.
"""

from __future__ import annotations

import pytest
from tests.unit.wiki.conftest import make_page, make_wiki
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.humanapproval.approval_errors import ConfirmationRequiredError
from ygo74.agent_runtime.domains.humanapproval.broker import ConfirmationBroker
from ygo74.agent_runtime.domains.humanapproval.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationDecision,
    ConfirmationGate,
    ConfirmationOutcome,
    InMemoryConfirmationPreferenceStore,
)
from ygo74.agent_runtime.domains.humanapproval.ledger import InMemoryConfirmationLedger
from ygo74.agent_runtime.domains.humanapproval.unattended import UnattendedApprovalAuthority
from ygo74.agent_runtime.domains.security.audit import InMemoryAuditTrail
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.core.config.manifests import AgentManifestLoader, SkillManifestLoader
from ai_agent_lab.wiki.application.confirmation_presenter import (
    UnknownGatedWikiToolError,
    WikiConfirmationPresenter,
)
from ai_agent_lab.wiki.application.skills_factory import WikiSkills, WikiSkillsFactory
from ai_agent_lab.wiki.capabilities.write_capabilities import (
    DRAFT_PAGE_CONTENT,
    WikiWriteCapabilities,
)
from ai_agent_lab.wiki.catalog import DeliveredWikiOperations, WikiToolName
from ai_agent_lab.wiki.domain.errors import WikiDraftNotFoundError
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.inmemory.draft_store import InMemoryWikiDraftStore
from ai_agent_lab.wiki.inmemory.wiki import PageEntry
from ai_agent_lab.wiki.inmemory.wiki_tools import InMemoryWikiTools
from ai_agent_lab.wiki.security_floor import WikiSecurityFloor
from ai_agent_lab.wiki.skills.analysis import PageDraftOutput
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.freshness_skill import PageFreshnessDetector
from ai_agent_lab.wiki.skills.gating import GatedWikiOperationRunner

DRAFTED_BODY = "A body the model composed."


class DraftingReasoner:
    """Returns a fixed composed page without reaching a model."""

    def __init__(self, body: str = DRAFTED_BODY, title: str = "Charter") -> None:
        self._output = PageDraftOutput(title=title, body=body)

    async def reason(self, request: object, response_model: type) -> object:
        """Return the prepared draft."""
        del request, response_model
        return self._output


def load_manifest() -> AgentManifest:
    """Load the delivered wiki manifest, floor included."""
    directory = ConfigurationDirectory.resolve()
    skills = SkillManifestLoader(
        PermissionRegistry(WikiPermission.declared()),
        WikiSecurityFloor().build(),
    )
    return AgentManifestLoader(directory, skills).load("wiki")


@pytest.fixture
def manifest() -> AgentManifest:
    """The delivered configuration of the Wiki Agent."""
    return load_manifest()


@pytest.fixture
def tools() -> InMemoryWikiTools:
    """A small wiki holding one page."""
    return InMemoryWikiTools(make_wiki(PageEntry(make_page(page_id="p1", version=2))))


@pytest.fixture
def ledger() -> InMemoryConfirmationLedger:
    """The ledger carrying answers from the host to the domain."""
    return InMemoryConfirmationLedger()


@pytest.fixture
def store() -> InMemoryWikiDraftStore:
    """The store holding prepared page drafts."""
    return InMemoryWikiDraftStore()


@pytest.fixture
def skills(manifest: AgentManifest, tools: InMemoryWikiTools) -> WikiSkills:
    """Every wiki skill, over the small wiki and a scripted reasoner."""
    policy = ConfiguredConfirmationPolicy(
        InMemoryConfirmationPreferenceStore({}), WikiSecurityFloor().build()
    )
    return WikiSkillsFactory(
        wiki_tools=tools,
        reasoner=DraftingReasoner(),
        manifest=manifest,
        context_builder=WikiContextBuilder(),
        freshness_detector=PageFreshnessDetector(ageing_after_days=90, stale_after_days=180),
        runner=GatedWikiOperationRunner(
            DeliveredWikiOperations(manifest),
            policy,
            ConfirmationGate(policy),
            InMemoryAuditTrail(),
        ),
    ).build()


@pytest.fixture
def capabilities(
    manifest: AgentManifest,
    skills: WikiSkills,
    store: InMemoryWikiDraftStore,
    ledger: InMemoryConfirmationLedger,
) -> dict[str, object]:
    """The write capabilities, by tool name."""
    descriptors = WikiWriteCapabilities(
        manifest,
        skills.drafting,
        skills.authoring,
        skills.comment,
        store,
        ConfirmationBroker(UnattendedApprovalAuthority(), ledger),
    ).descriptors()
    return {descriptor.tool_name: descriptor for descriptor in descriptors}


@pytest.fixture
def presenter(skills: WikiSkills, store: InMemoryWikiDraftStore) -> WikiConfirmationPresenter:
    """The presenter turning a suspended call into a readable request."""
    return WikiConfirmationPresenter(skills, store)


async def run(capability, arguments: dict, user) -> object:
    """Invoke a capability the way the framework adapter does."""
    return await capability.invoke(capability.input_model.model_validate(arguments), user)


def approve(ledger: InMemoryConfirmationLedger, request, user) -> None:
    """Record the answer a host would have collected from the user."""
    ledger.record(
        ConfirmationOutcome(
            request=request,
            decision=ConfirmationDecision(
                request_id=request.request_id, approved=True, decided_by=user.user_id
            ),
        ),
        user,
    )


class TestDeliveredCapabilities:
    """What the manifest actually offers."""

    def test_the_five_write_capabilities_are_built(self, capabilities):
        assert set(capabilities) == {
            DRAFT_PAGE_CONTENT,
            WikiToolName.CREATE_PAGE.value,
            WikiToolName.UPDATE_PAGE.value,
            WikiToolName.ADD_COMMENT.value,
            WikiToolName.DELETE_PAGE.value,
        }

    def test_drafting_is_declared_as_a_read(self, capabilities):
        """It composes text and touches nothing."""
        assert not capabilities[DRAFT_PAGE_CONTENT].operation.is_write

    def test_the_page_writes_are_declared_as_writes(self, capabilities):
        for name in (WikiToolName.CREATE_PAGE.value, WikiToolName.UPDATE_PAGE.value):
            assert capabilities[name].operation.is_write


class TestDrafting:
    """Composing content, which must never reach the wiki."""

    async def test_a_revision_carries_the_version_it_was_composed_against(
        self, capabilities, author, store
    ):
        result = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"page_id": "p1", "instruction": "mention the queue"},
            author,
        )

        draft = store.get(result.draft_reference, author)
        assert draft.expected_version == 2
        assert draft.page_id == "p1"

    async def test_drafting_writes_nothing(self, capabilities, author, tools):
        await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"page_id": "p1", "instruction": "rewrite everything"},
            author,
        )

        page = await tools.get_page("p1", author)
        assert page.version == 2
        assert DRAFTED_BODY not in page.body.expose()

    async def test_a_new_page_draft_names_its_space(self, capabilities, author, store):
        result = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"space_key": "APOLLO", "title": "Runbook", "instruction": "how to deploy"},
            author,
        )

        draft = store.get(result.draft_reference, author)
        assert draft.space_key == "APOLLO"
        assert draft.page_id is None


@pytest.mark.security
class TestTheApprovalIsRequired:
    """A gated capability cannot run on nobody's authority."""

    async def test_an_unanswered_write_reaches_no_wiki(self, capabilities, author, store, tools):
        result = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"page_id": "p1", "instruction": "mention the queue"},
            author,
        )

        with pytest.raises(ConfirmationRequiredError):
            await run(
                capabilities[WikiToolName.UPDATE_PAGE.value],
                {"draft_reference": result.draft_reference},
                author,
            )

        assert (await tools.get_page("p1", author)).version == 2
        assert store.get(result.draft_reference, author) is not None

    async def test_an_answered_write_runs(self, capabilities, presenter, ledger, author, tools):
        drafted = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"page_id": "p1", "instruction": "mention the queue"},
            author,
        )
        arguments = {"draft_reference": drafted.draft_reference}
        approve(ledger, await presenter.present(WikiToolName.UPDATE_PAGE.value, arguments, author), author)

        await run(capabilities[WikiToolName.UPDATE_PAGE.value], arguments, author)

        page = await tools.get_page("p1", author)
        assert page.body.expose() == DRAFTED_BODY
        assert page.version == 3


@pytest.mark.security
class TestTheConfirmationKeysAgree:
    """The presenter and the capability must name the same operation.

    Asserted through the ledger rather than by comparing keys directly, because
    the ledger lookup is what actually happens at runtime: a key the capability
    cannot find is a key that does not exist, however similar it looks.
    """

    async def test_an_update_finds_the_answer_the_user_gave(
        self, capabilities, presenter, ledger, author
    ):
        drafted = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"page_id": "p1", "instruction": "mention the queue"},
            author,
        )
        arguments = {"draft_reference": drafted.draft_reference}
        approve(ledger, await presenter.present(WikiToolName.UPDATE_PAGE.value, arguments, author), author)

        await run(capabilities[WikiToolName.UPDATE_PAGE.value], arguments, author)

        assert ledger.pending_count(author) == 0

    async def test_a_creation_finds_the_answer_the_user_gave(
        self, capabilities, presenter, ledger, author
    ):
        drafted = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"space_key": "APOLLO", "title": "Runbook", "instruction": "how to deploy"},
            author,
        )
        arguments = {"draft_reference": drafted.draft_reference}
        approve(ledger, await presenter.present(WikiToolName.CREATE_PAGE.value, arguments, author), author)

        await run(capabilities[WikiToolName.CREATE_PAGE.value], arguments, author)

        assert ledger.pending_count(author) == 0

    async def test_a_comment_finds_the_answer_the_user_gave(
        self, capabilities, presenter, ledger, author
    ):
        arguments = {"page_id": "p1", "body": "A remark."}
        approve(ledger, await presenter.present(WikiToolName.ADD_COMMENT.value, arguments, author), author)

        await run(capabilities[WikiToolName.ADD_COMMENT.value], arguments, author)

        assert ledger.pending_count(author) == 0

    async def test_a_deletion_finds_the_answer_the_user_gave(
        self, capabilities, presenter, ledger, author
    ):
        arguments = {"page_id": "p1"}
        approve(ledger, await presenter.present(WikiToolName.DELETE_PAGE.value, arguments, author), author)

        await run(capabilities[WikiToolName.DELETE_PAGE.value], arguments, author)

        assert ledger.pending_count(author) == 0


@pytest.mark.security
class TestThePresenterShowsWhatWillHappen:
    """What a person reads before deciding."""

    async def test_an_update_shows_the_composed_body(self, capabilities, presenter, author):
        drafted = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"page_id": "p1", "instruction": "mention the queue"},
            author,
        )

        request = await presenter.present(
            WikiToolName.UPDATE_PAGE.value, {"draft_reference": drafted.draft_reference}, author
        )

        shown = {detail.label: detail.value for detail in request.details}
        assert shown["New body"] == DRAFTED_BODY

    async def test_another_person_draft_cannot_be_presented(self, capabilities, presenter, author, reader):
        """A reference issued to one person is worthless to another."""
        drafted = await run(
            capabilities[DRAFT_PAGE_CONTENT],
            {"page_id": "p1", "instruction": "mention the queue"},
            author,
        )

        with pytest.raises(WikiDraftNotFoundError):
            await presenter.present(
                WikiToolName.UPDATE_PAGE.value, {"draft_reference": drafted.draft_reference}, reader
            )

    async def test_a_capability_that_cannot_be_described_is_refused(self, presenter, author):
        """Approving an operation nobody can explain would be worse than failing."""
        with pytest.raises(UnknownGatedWikiToolError):
            await presenter.present("search_wiki", {}, author)


class TestTheDraftIsWhatGetsWritten:
    """A model cannot substitute content after the approval."""

    @pytest.mark.security
    async def test_the_write_takes_no_body_from_the_model(self, capabilities):
        """The publishing capabilities accept a reference and nothing else."""
        for name in (WikiToolName.CREATE_PAGE.value, WikiToolName.UPDATE_PAGE.value):
            fields = set(capabilities[name].input_model.model_fields)
            assert fields == {"draft_reference"}

    @pytest.mark.security
    async def test_an_unknown_reference_writes_nothing(self, capabilities, author, tools):
        with pytest.raises(WikiDraftNotFoundError):
            await run(
                capabilities[WikiToolName.UPDATE_PAGE.value],
                {"draft_reference": "wiki-draft-forged"},
                author,
            )

        assert (await tools.get_page("p1", author)).version == 2
