"""Tests of the state-changing mail skills."""

from __future__ import annotations

import pytest
from tests.conftest import make_message
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
from ygo74.agent_runtime.domains.security.operations import RiskLevel
from ygo74.agent_runtime.domains.security.security_errors import PermissionDeniedError, SecurityError
from ygo74.agent_runtime.domains.security.untrusted import untrusted
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.catalog import MailToolCatalog, MailToolName
from ai_agent_lab.mail.config.mailbox_directory import ConfiguredMailboxOwnerDirectory
from ai_agent_lab.mail.domain.errors import NoReplyRecipientError
from ai_agent_lab.mail.domain.models import EmailAddress, MailDraft
from ai_agent_lab.mail.domain.origins import MailOrigin
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner
from ai_agent_lab.mail.security_floor import MailSecurityFloor
from ai_agent_lab.mail.skills.analysis import MailReplyOutput
from ai_agent_lab.mail.skills.gating import GatedMailOperationRunner
from ai_agent_lab.mail.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.skills.reply_skill import MailReplySkill, ReplyRecipientPlanner
from ai_agent_lab.mail.skills.send_skill import SendMailSkill

REPLY_ANSWER = {"subject": "Re: Project Alpha - architecture review", "body": "Agreed. I will review it tomorrow."}

# Reasoning instructions are delivered configuration, so a unit test supplies
# its own rather than depending on the wording shipped in config/.
REPLY_PROMPT = "Draft a reply. Do not add recipients and do not invent commitments."


@pytest.fixture
def audit():
    """Audit trail capturing every state-changing attempt."""
    return InMemoryAuditTrail()


@pytest.fixture
def preference_store():
    """Per-user confirmation preferences, empty by default."""
    return InMemoryConfirmationPreferenceStore()


@pytest.fixture
def runner(audit, preference_store):
    """Runner enforcing the confirmation policy and writing the audit trail."""
    policy = ConfiguredConfirmationPolicy(preference_store, MailSecurityFloor().build())
    return GatedMailOperationRunner(MailToolCatalog(), policy, ConfirmationGate(policy), audit)


@pytest.fixture
def send_skill(mail_tools, runner):
    """The delivery skill under test."""
    return SendMailSkill(mail_tools, mail_tools, runner)


@pytest.fixture
def management_skill(mail_tools, runner):
    """The housekeeping skill under test."""
    return MailManagementSkill(mail_tools, mail_tools, mail_tools, runner)


@pytest.fixture
def reply_skill(mail_tools, context_builder, envelope_builder):
    """The drafting skill under test."""
    return MailReplySkill(
        mail_tools,
        ScriptedTextReasoner({MailReplyOutput: REPLY_ANSWER}, envelope_builder=envelope_builder),
        context_builder,
        ConfiguredMailboxOwnerDirectory({"owner": "owner@example.com"}),
        ReplyRecipientPlanner(),
        REPLY_PROMPT,
    )


def draft(to: str = "john@example.com", in_reply_to: str | None = "m1") -> MailDraft:
    """Build a minimal draft."""
    return MailDraft(
        to=(EmailAddress(value=to),),
        subject=untrusted("Re: Project Alpha", MailOrigin.SUBJECT),
        body=untrusted("Agreed.", MailOrigin.BODY),
        in_reply_to_message_id=in_reply_to,
    )


class TestMailReplySkill:
    """Drafting a reply, without ever delivering it."""

    async def test_drafts_a_reply_to_a_message(self, reply_skill, owner):
        result = await reply_skill.draft_reply_to_message("m1", "Say I agree", owner)

        assert result.body.expose() == "Agreed. I will review it tomorrow."
        assert result.in_reply_to_message_id == "m1"

    async def test_addresses_the_reply_to_the_original_sender(self, reply_skill, owner):
        result = await reply_skill.draft_reply_to_message("m1", "Say I agree", owner)

        assert [str(address) for address in result.to] == ["john@example.com"]
        assert result.cc == ()

    async def test_replies_to_the_latest_message_of_a_thread(self, reply_skill, owner):
        result = await reply_skill.draft_reply_to_thread("t1", "Say I agree", owner)

        assert result.in_reply_to_message_id == "m2"
        assert [str(address) for address in result.to] == ["sarah@example.com"]

    async def test_never_sends_anything(self, reply_skill, mail_tools, owner):
        await reply_skill.draft_reply_to_message("m1", "Say I agree", owner)

        assert mail_tools.mailbox_of(owner).sent == ()

    async def test_never_saves_a_draft_by_itself(self, reply_skill, mail_tools, owner):
        await reply_skill.draft_reply_to_message("m1", "Say I agree", owner)

        assert mail_tools.mailbox_of(owner).drafts == ()

    async def test_derives_a_subject_when_the_reasoner_returns_none(self, mail_tools, context_builder, owner):
        skill = MailReplySkill(
            mail_tools,
            ScriptedTextReasoner({MailReplyOutput: {"subject": "  ", "body": "ok"}}),
            context_builder,
            ConfiguredMailboxOwnerDirectory({"owner": "owner@example.com"}),
            ReplyRecipientPlanner(),
            REPLY_PROMPT,
        )

        result = await skill.draft_reply_to_message("m1", "Say I agree", owner)

        assert result.subject.expose() == "Re: Project Alpha - architecture review"

    @pytest.mark.security
    async def test_requires_the_draft_permission(self, reply_skill):
        reader = UserContext(user_id="owner", session_id="s", permissions=frozenset({MailPermission.READ}))

        with pytest.raises(PermissionDeniedError):
            await reply_skill.draft_reply_to_message("m1", "Say I agree", reader)


class TestReplyRecipientPlanner:
    """Deterministic choice of the recipients of a reply."""

    def test_reply_targets_the_sender_only(self):
        message = make_message(sender="john@example.com", to=("owner@example.com", "sarah@example.com"))

        to, cc = ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=False)

        assert [str(address) for address in to] == ["john@example.com"]
        assert cc == ()

    def test_reply_all_keeps_the_other_participants_in_copy(self):
        message = make_message(sender="john@example.com", to=("owner@example.com", "sarah@example.com"))

        to, cc = ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=True)

        assert [str(address) for address in to] == ["john@example.com"]
        assert [str(address) for address in cc] == ["sarah@example.com"]

    def test_the_owner_is_never_a_recipient_of_their_own_reply(self):
        message = make_message(sender="john@example.com", to=("owner@example.com",))

        to, cc = ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=True)

        assert "owner@example.com" not in {str(a) for a in (*to, *cc)}

    def test_replying_to_own_message_promotes_the_recipients(self):
        message = make_message(sender="owner@example.com", to=("john@example.com",))

        to, cc = ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=True)

        assert [str(address) for address in to] == ["john@example.com"]
        assert cc == ()

    def test_refuses_to_build_a_reply_with_no_recipient(self):
        message = make_message(sender="owner@example.com", to=("owner@example.com",))

        with pytest.raises(NoReplyRecipientError):
            ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=True)


class TestSendMailSkill:
    """Delivery, gated by an explicit confirmation."""

    async def test_saving_a_draft_does_not_require_confirmation(self, send_skill, mail_tools, owner):
        saved = await send_skill.save_draft(draft(), owner)

        assert saved.draft_id
        assert mail_tools.mailbox_of(owner).sent == ()

    async def test_reports_that_sending_requires_confirmation(self, send_skill, owner):
        assert send_skill.requires_confirmation(owner)

    async def test_the_confirmation_request_shows_what_will_be_sent(self, send_skill, owner):
        request = send_skill.build_confirmation_request(draft(), owner)

        labels = {detail.label: detail.value for detail in request.details}
        assert labels["To"] == "john@example.com"
        assert labels["Subject"] == "Re: Project Alpha"
        assert request.operation.tool_name == MailToolName.SEND_MAIL.value
        assert request.requested_for == owner.user_id

    @pytest.mark.security
    async def test_refuses_to_send_without_a_confirmation(self, send_skill, mail_tools, owner):
        with pytest.raises(ConfirmationRequiredError):
            await send_skill.send(draft(), owner)

        assert mail_tools.mailbox_of(owner).sent == ()

    @pytest.mark.security
    async def test_refuses_to_send_when_the_user_declines(self, send_skill, mail_tools, owner):
        request = send_skill.build_confirmation_request(draft(), owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=False, decided_by="owner")

        with pytest.raises(ConfirmationRejectedError):
            await send_skill.send(draft(), owner, request=request, decision=decision)

        assert mail_tools.mailbox_of(owner).sent == ()

    @pytest.mark.security
    async def test_refuses_a_confirmation_issued_for_another_request(self, send_skill, mail_tools, owner):
        request = send_skill.build_confirmation_request(draft(), owner)
        replayed = ConfirmationDecision(request_id="cfm-other", approved=True, decided_by="owner")

        with pytest.raises(ConfirmationMismatchError):
            await send_skill.send(draft(), owner, request=request, decision=replayed)

        assert mail_tools.mailbox_of(owner).sent == ()

    async def test_sends_exactly_once_after_an_approval(self, send_skill, mail_tools, owner):
        request = send_skill.build_confirmation_request(draft(), owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="owner")

        result = await send_skill.send(draft(), owner, request=request, decision=decision)

        assert result.message_id
        assert len(mail_tools.mailbox_of(owner).sent) == 1

    @pytest.mark.security
    async def test_sending_cannot_be_auto_approved_by_preferences(self, mail_tools, audit, preference_store, owner):
        preference_store.set_preferences(
            "owner", ConfirmationPreferences(auto_approved_tools=frozenset({MailToolName.SEND_MAIL.value}))
        )
        policy = ConfiguredConfirmationPolicy(preference_store, MailSecurityFloor().build())
        runner = GatedMailOperationRunner(MailToolCatalog(), policy, ConfirmationGate(policy), audit)
        skill = SendMailSkill(mail_tools, mail_tools, runner)

        with pytest.raises(ConfirmationRequiredError):
            await skill.send(draft(), owner)

    @pytest.mark.security
    async def test_requires_the_send_permission(self, send_skill, mail_tools):
        limited = UserContext(user_id="owner", session_id="s", permissions=frozenset({MailPermission.READ}))

        with pytest.raises(PermissionDeniedError):
            await send_skill.send(draft(), limited)

        assert mail_tools.mailbox_of(limited).sent == ()

    async def test_records_an_approved_delivery(self, send_skill, audit, owner):
        request = send_skill.build_confirmation_request(draft(), owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="owner")

        await send_skill.send(draft(), owner, request=request, decision=decision)

        entry = audit.records_for(MailToolName.SEND_MAIL.value)[0]
        assert entry.outcome is AuditOutcome.EXECUTED
        assert entry.confirmation_request_id == request.request_id

    async def test_records_a_declined_delivery(self, send_skill, audit, owner):
        request = send_skill.build_confirmation_request(draft(), owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=False, decided_by="owner")

        with pytest.raises(ConfirmationRejectedError):
            await send_skill.send(draft(), owner, request=request, decision=decision)

        assert audit.records_for(MailToolName.SEND_MAIL.value)[0].outcome is AuditOutcome.DECLINED

    @pytest.mark.security
    async def test_the_audit_trail_never_holds_message_content(self, send_skill, audit, owner):
        request = send_skill.build_confirmation_request(draft(), owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="owner")

        await send_skill.send(draft(), owner, request=request, decision=decision)

        serialised = audit.records[0].model_dump_json()
        assert "Agreed." not in serialised
        assert "Re: Project Alpha" not in serialised
        assert "john@example.com" not in serialised


class TestMailManagementSkill:
    """Housekeeping, gated by the same policy as delivery."""

    @pytest.mark.parametrize(
        ("tool", "call"),
        [
            (MailToolName.MARK_READ, lambda skill, user: skill.set_read_state("m1", True, user)),
            (MailToolName.ARCHIVE_MAIL, lambda skill, user: skill.archive("m1", user)),
            (MailToolName.APPLY_LABEL, lambda skill, user: skill.apply_label("m1", "PROJECT", user)),
            (MailToolName.REMOVE_LABEL, lambda skill, user: skill.remove_label("m1", "PROJECT", user)),
        ],
    )
    @pytest.mark.security
    async def test_every_operation_refuses_to_run_unconfirmed(self, management_skill, mail_tools, owner, tool, call):
        with pytest.raises(ConfirmationRequiredError):
            await call(management_skill, owner)

        message = await mail_tools.get_message("m1", owner)
        assert not message.is_read
        assert not message.is_archived
        assert message.label_ids == ()

    async def test_marks_a_message_as_read_after_approval(self, management_skill, mail_tools, owner):
        await self._approve(management_skill, MailToolName.MARK_READ, "m1", owner, is_read=True)

        assert (await mail_tools.get_message("m1", owner)).is_read

    async def test_archives_a_message_after_approval(self, management_skill, mail_tools, owner):
        request = management_skill.build_confirmation_request(MailToolName.ARCHIVE_MAIL, "m1", owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="owner")

        await management_skill.archive("m1", owner, request=request, decision=decision)

        assert (await mail_tools.get_message("m1", owner)).is_archived

    async def test_applies_and_removes_a_label_after_approval(self, management_skill, mail_tools, owner):
        apply_request = management_skill.build_confirmation_request(
            MailToolName.APPLY_LABEL, "m1", owner, label_id="PROJECT"
        )
        await management_skill.apply_label(
            "m1",
            "PROJECT",
            owner,
            request=apply_request,
            decision=ConfirmationDecision(request_id=apply_request.request_id, approved=True, decided_by="owner"),
        )

        assert "PROJECT" in (await mail_tools.get_message("m1", owner)).label_ids

        remove_request = management_skill.build_confirmation_request(
            MailToolName.REMOVE_LABEL, "m1", owner, label_id="PROJECT"
        )
        await management_skill.remove_label(
            "m1",
            "PROJECT",
            owner,
            request=remove_request,
            decision=ConfirmationDecision(request_id=remove_request.request_id, approved=True, decided_by="owner"),
        )

        assert "PROJECT" not in (await mail_tools.get_message("m1", owner)).label_ids

    async def test_mark_read_can_be_auto_approved_by_preferences(self, mail_tools, audit, preference_store, owner):
        preference_store.set_preferences(
            "owner", ConfirmationPreferences(auto_approved_tools=frozenset({MailToolName.MARK_READ.value}))
        )
        policy = ConfiguredConfirmationPolicy(preference_store, MailSecurityFloor().build())
        runner = GatedMailOperationRunner(MailToolCatalog(), policy, ConfirmationGate(policy), audit)
        skill = MailManagementSkill(mail_tools, mail_tools, mail_tools, runner)

        await skill.set_read_state("m1", True, owner)

        assert (await mail_tools.get_message("m1", owner)).is_read

    async def test_listing_labels_needs_no_confirmation(self, management_skill, owner):
        labels = await management_skill.list_labels(owner)

        assert {label.label_id for label in labels} == {"INBOX", "PROJECT"}

    async def test_records_a_blocked_operation(self, management_skill, audit, owner):
        with pytest.raises(ConfirmationRequiredError):
            await management_skill.archive("m1", owner)

        assert audit.records_for(MailToolName.ARCHIVE_MAIL.value)[0].outcome is AuditOutcome.BLOCKED

    async def test_records_a_failed_operation(self, management_skill, audit, owner):
        from ai_agent_lab.mail.mail_errors import MailNotFoundError

        request = management_skill.build_confirmation_request(MailToolName.ARCHIVE_MAIL, "absent", owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="owner")

        with pytest.raises(MailNotFoundError):
            await management_skill.archive("absent", owner, request=request, decision=decision)

        entry = audit.records_for(MailToolName.ARCHIVE_MAIL.value)[0]
        assert entry.outcome is AuditOutcome.FAILED
        assert entry.error_type == "MailNotFoundError"

    @staticmethod
    async def _approve(skill, tool, message_id, user, **kwargs):
        """Build a request, approve it and run the matching operation."""
        request = skill.build_confirmation_request(tool, message_id, user, **kwargs)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by=user.user_id)
        await skill.set_read_state(message_id, kwargs["is_read"], user, request=request, decision=decision)


class TestLabelLifecycle:
    """Creating and deleting labels, gated like every other write."""

    async def test_creating_a_label_needs_no_confirmation_by_default(self, management_skill, owner):
        """Creating a label destroys nothing, so it is not gated out of the box."""
        outcome = await management_skill.create_label("Invoices", owner)

        assert outcome.created
        assert outcome.label.name.expose() == "Invoices"

    async def test_creating_a_label_can_be_gated_by_preferences(self, mail_tools, audit, preference_store, owner):
        """A deployment that wants the model to ask can say so, in configuration."""
        preference_store.set_preferences(
            "owner", ConfirmationPreferences(always_confirm_tools=frozenset({MailToolName.CREATE_LABEL.value}))
        )
        policy = ConfiguredConfirmationPolicy(preference_store, MailSecurityFloor().build())
        runner = GatedMailOperationRunner(MailToolCatalog(), policy, ConfirmationGate(policy), audit)
        skill = MailManagementSkill(mail_tools, mail_tools, mail_tools, runner)

        with pytest.raises(ConfirmationRequiredError):
            await skill.create_label("Invoices", owner)

    @pytest.mark.security
    async def test_deleting_a_label_refuses_to_run_unconfirmed(self, management_skill, mail_tools, owner):
        with pytest.raises(ConfirmationRequiredError):
            await management_skill.delete_label("PROJECT", owner)

        assert "PROJECT" in {label.label_id for label in await mail_tools.list_labels(owner)}

    async def test_deleting_a_label_after_approval(self, management_skill, mail_tools, owner):
        request = management_skill.build_label_confirmation_request(MailToolName.DELETE_LABEL, "PROJECT", owner)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="owner")

        await management_skill.delete_label("PROJECT", owner, request=request, decision=decision)

        assert "PROJECT" not in {label.label_id for label in await mail_tools.list_labels(owner)}

    @pytest.mark.security
    async def test_the_confirmation_names_the_label_it_is_about(self, management_skill, owner):
        """The presenter and the capability must name the same target.

        Otherwise the answer the user gives could be matched to a different
        operation than the one they were shown.
        """
        request = management_skill.build_label_confirmation_request(MailToolName.DELETE_LABEL, "PROJECT", owner)

        assert request.target == "PROJECT"
        assert any(detail.value == "PROJECT" for detail in request.details)
        assert request.operation.risk_level is RiskLevel.HIGH

    @pytest.mark.security
    async def test_a_deletion_approval_cannot_be_replayed_on_another_label(self, management_skill, mail_tools, owner):
        approved = management_skill.build_label_confirmation_request(MailToolName.DELETE_LABEL, "PROJECT", owner)
        decision = ConfirmationDecision(request_id=approved.request_id, approved=True, decided_by="owner")
        other = management_skill.build_label_confirmation_request(MailToolName.DELETE_LABEL, "INBOX", owner)

        with pytest.raises(SecurityError):
            await management_skill.delete_label("INBOX", owner, request=other, decision=decision)

        assert "INBOX" in {label.label_id for label in await mail_tools.list_labels(owner)}

    async def test_a_blocked_deletion_is_audited(self, management_skill, audit, owner):
        with pytest.raises(ConfirmationRequiredError):
            await management_skill.delete_label("PROJECT", owner)

        entry = audit.records_for(MailToolName.DELETE_LABEL.value)[0]
        assert entry.outcome is AuditOutcome.BLOCKED
        assert entry.target_id == "PROJECT"
