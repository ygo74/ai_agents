"""Tests of saving a prepared reply into the mailbox.

Drafting produces a reply that exists only inside the agent. That is deliberate -
composing must never touch the mailbox - but it leaves a gap a user notices
immediately: they are told a draft is ready, go to look for it, and it is
nowhere. The mailbox has never heard of it.

Closing that gap is a separate capability rather than a side effect of drafting,
so composing stays free of consequences and putting something in the mailbox
stays an act the user asked for.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.maf_fakes import ScriptedChatClient, says
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.capabilities.results import DraftPreparedResult, DraftSavedResult
from ai_agent_lab.mail.capabilities.tool_inputs import DraftReferenceInput, DraftReplyInput
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.domain.errors import DraftNotFoundError
from ai_agent_lab.mail.domain.models import MailDraft
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner
from ai_agent_lab.mail.skills.analysis import MailReplyOutput

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPOSITORY_ROOT / "data" / "mail" / "sample_mailbox.json"
MESSAGE_ID = "m-alpha-1"
OWNER = "local-user"
SAVE = MailToolName.CREATE_DRAFT.value


class Mailbox:
    """A Mail Agent over the sample mailbox, with the mailbox observable."""

    def __init__(self):
        self.tools = InMemoryMailTools(MailDatasetLoader().load_file(DATASET))
        self.runtime = MailAgentCompositionRoot(
            MailAgentSettings(user_id=OWNER, user_email="local-user@example.com"),
            ScriptedChatClient([says("nothing to do")]),
            mail_tools=self.tools,
            reasoner=ScriptedTextReasoner(
                {MailReplyOutput: MailReplyOutput(subject="Re: Project Alpha", body="Will review by Friday.")}
            ),
            base_path=REPOSITORY_ROOT,
        ).build(session_id="drafts")

    @property
    def user(self) -> UserContext:
        """The identity every capability call carries."""
        return self.runtime.user

    @property
    def stored_drafts(self) -> tuple[MailDraft, ...]:
        """The drafts the mailbox itself holds."""
        return self.tools.mailbox_of(self.user).drafts

    def offers(self, tool_name: str) -> bool:
        """Whether the agent exposes a capability to the model."""
        return any(descriptor.tool_name == tool_name for descriptor in self.runtime.registry.skills)

    async def invoke(self, tool_name: str, payload):
        """Run one capability the way the framework adapter would."""
        descriptor = self.runtime.registry.skill(tool_name)
        return await descriptor.invoke(descriptor.input_model.model_validate(payload), self.user)

    async def prepare(self) -> DraftPreparedResult:
        """Draft a reply, as the model would before saving it."""
        result = await self.invoke(
            "draft_mail_reply",
            DraftReplyInput(message_id=MESSAGE_ID, intent="say I will review it"),
        )
        assert isinstance(result, DraftPreparedResult)
        return result

    async def save(self, reference: str) -> DraftSavedResult:
        """Put a prepared draft in the mailbox."""
        result = await self.invoke(SAVE, DraftReferenceInput(draft_reference=reference))
        assert isinstance(result, DraftSavedResult)
        return result


@pytest.mark.asyncio
class TestSavingAPreparedDraft:
    async def test_the_capability_is_offered(self):
        """Without it a draft can be composed but never kept anywhere."""
        assert Mailbox().offers(SAVE)

    async def test_the_draft_reaches_the_mailbox(self):
        mailbox = Mailbox()
        prepared = await mailbox.prepare()

        await mailbox.save(prepared.draft_reference)

        assert [draft.subject.expose() for draft in mailbox.stored_drafts] == [prepared.subject]

    async def test_the_mailbox_identifier_is_reported(self):
        """The user is told where it landed, not merely that it did."""
        mailbox = Mailbox()

        saved = await mailbox.save((await mailbox.prepare()).draft_reference)

        assert saved.draft_id
        assert saved.draft_id == mailbox.stored_drafts[-1].draft_id

    async def test_the_reference_survives_saving(self):
        """Saving must not consume what the send step still needs."""
        mailbox = Mailbox()
        prepared = await mailbox.prepare()

        first = await mailbox.save(prepared.draft_reference)
        second = await mailbox.save(prepared.draft_reference)

        assert first.draft_reference == prepared.draft_reference
        assert second.draft_reference == prepared.draft_reference

    async def test_drafting_alone_stores_nothing(self):
        """Composing has no consequence: that is why saving exists separately."""
        mailbox = Mailbox()

        await mailbox.prepare()

        assert mailbox.stored_drafts == ()

    async def test_saving_delivers_nothing(self):
        """A draft in the mailbox is not a message anybody received."""
        mailbox = Mailbox()

        await mailbox.save((await mailbox.prepare()).draft_reference)

        assert mailbox.tools.mailbox_of(mailbox.user).sent == ()


@pytest.mark.asyncio
@pytest.mark.security
class TestSavingIsGovernedLikeAnyWrite:
    async def test_an_invented_reference_saves_nothing(self):
        """A model must not be able to conjure a draft nobody prepared."""
        mailbox = Mailbox()

        with pytest.raises(DraftNotFoundError):
            await mailbox.invoke(SAVE, DraftReferenceInput(draft_reference="draft-000000000000"))

        assert mailbox.stored_drafts == ()

    async def test_it_requires_the_drafting_permission(self):
        mailbox = Mailbox()

        descriptor = mailbox.runtime.registry.skill(SAVE)

        assert descriptor.operation.required_permission == MailPermission.DRAFT
        assert descriptor.operation.is_write
