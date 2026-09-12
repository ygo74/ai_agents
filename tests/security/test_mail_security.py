"""Security tests of the Mail Agent.

These tests describe attacks rather than features. They exist to fail loudly if
a refactoring ever weakens a boundary: cross-mailbox access, confirmation
bypass, prompt injection or data leaking into logs and traces.
"""

from __future__ import annotations

import logging
from datetime import UTC

import pytest
from tests.unit.test_mail_dataset import SAMPLE_DATASET

from ai_agent_lab.core.observability.audit import InMemoryAuditTrail, LoggingAuditTrail
from ai_agent_lab.core.security.audit import AuditOutcome
from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationDecision,
    ConfirmationGate,
    ConfirmationPreferences,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.errors import (
    AuthorizationError,
    ConfirmationMismatchError,
    ConfirmationRejectedError,
    ConfirmationRequiredError,
)
from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.mail.catalog import MailToolCatalog, MailToolName
from ai_agent_lab.mail.domain.errors import DraftNotFoundError
from ai_agent_lab.mail.domain.models import EmailAddress, MailDraft, MailSearchRequest
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.inmemory.draft_store import InMemoryDraftStore
from ai_agent_lab.mail.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mail.mail_errors import MailAccessDeniedError, MailToolError
from ai_agent_lab.mail.security_floor import MailSecurityFloor
from ai_agent_lab.mail.skills.gating import GatedMailOperationRunner
from ai_agent_lab.mail.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.skills.search_skill import MailReadSkill, MailSearchSkill
from ai_agent_lab.mail.skills.send_skill import SendMailSkill

LOCAL_USER = UserContext(user_id="local-user", session_id="s1", permissions=MailPermission.declared())
OTHER_USER = UserContext(user_id="other-user", session_id="s2", permissions=MailPermission.declared())

pytestmark = pytest.mark.security


@pytest.fixture
def mail_tools():
    """Mail tools serving two distinct mailboxes."""
    return InMemoryMailTools(MailDatasetLoader().load_file(SAMPLE_DATASET))


@pytest.fixture
def audit():
    """Audit trail capturing every state-changing attempt."""
    return InMemoryAuditTrail()


@pytest.fixture
def runner(audit):
    """Runner applying the default confirmation policy."""
    policy = ConfiguredConfirmationPolicy(InMemoryConfirmationPreferenceStore(), MailSecurityFloor().build())
    return GatedMailOperationRunner(MailToolCatalog(), policy, ConfirmationGate(policy), LoggingAuditTrail(audit))


class TestCrossMailboxAccess:
    """One user must never observe or alter another user's mailbox.

    Isolation shows up as either a refusal or a plain absence, depending on
    whether the caller has a mailbox at all. Both are acceptable outcomes and
    both are failures of the attempt, which is what these tests assert.
    """

    async def test_a_user_cannot_read_a_message_of_another_mailbox(self, mail_tools):
        skill = MailReadSkill(mail_tools)

        with pytest.raises(MailToolError):
            await skill.read_message("m-private-1", LOCAL_USER)

    async def test_a_search_never_returns_another_mailbox(self, mail_tools):
        skill = MailSearchSkill(mail_tools)

        result = await skill.search(MailSearchRequest(keywords="confidential"), LOCAL_USER)

        assert result.headers == ()

    async def test_an_unknown_caller_is_refused_outright(self, mail_tools):
        stranger = UserContext(user_id="stranger", session_id="s3", permissions=MailPermission.declared())

        with pytest.raises(MailAccessDeniedError):
            await MailReadSkill(mail_tools).read_message("m-alpha-1", stranger)

    async def test_a_user_cannot_alter_another_mailbox(self, mail_tools, runner):
        skill = MailManagementSkill(mail_tools, mail_tools, mail_tools, runner)
        request = skill.build_confirmation_request(MailToolName.ARCHIVE_MAIL, "m-alpha-1", OTHER_USER)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="other-user")

        with pytest.raises(MailToolError):
            await skill.archive("m-alpha-1", OTHER_USER, request=request, decision=decision)

        assert not (await mail_tools.get_message("m-alpha-1", LOCAL_USER)).is_archived

    def test_a_draft_reference_cannot_be_redeemed_by_another_user(self):
        store = InMemoryDraftStore()
        reference = store.put(_draft(), LOCAL_USER)

        with pytest.raises(DraftNotFoundError):
            store.get(reference, OTHER_USER)


class TestConfirmationBypass:
    """The confirmation policy must not be avoidable."""

    async def test_a_direct_skill_call_cannot_skip_the_confirmation(self, mail_tools, runner):
        skill = SendMailSkill(mail_tools, mail_tools, runner)

        with pytest.raises(ConfirmationRequiredError):
            await skill.send(_draft(), LOCAL_USER)

        assert mail_tools.mailbox_of(LOCAL_USER).sent == ()

    async def test_a_confirmation_cannot_be_replayed_across_operations(self, mail_tools, runner):
        management = MailManagementSkill(mail_tools, mail_tools, mail_tools, runner)
        send = SendMailSkill(mail_tools, mail_tools, runner)
        harmless = management.build_confirmation_request(MailToolName.MARK_READ, "m-alpha-1", LOCAL_USER, is_read=True)
        approval = ConfirmationDecision(request_id=harmless.request_id, approved=True, decided_by="local-user")

        with pytest.raises(ConfirmationMismatchError):
            await send.send(
                _draft(),
                LOCAL_USER,
                request=send.build_confirmation_request(_draft(), LOCAL_USER),
                decision=approval,
            )

        assert mail_tools.mailbox_of(LOCAL_USER).sent == ()

    async def test_an_approval_granted_by_another_user_is_refused(self, mail_tools, runner):
        skill = SendMailSkill(mail_tools, mail_tools, runner)
        request = skill.build_confirmation_request(_draft(), LOCAL_USER)
        borrowed = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="other-user")

        with pytest.raises(ConfirmationMismatchError):
            await skill.send(_draft(), LOCAL_USER, request=request, decision=borrowed)

        assert mail_tools.mailbox_of(LOCAL_USER).sent == ()

    async def test_a_request_issued_for_another_user_is_refused(self, mail_tools, runner):
        skill = SendMailSkill(mail_tools, mail_tools, runner)
        foreign = skill.build_confirmation_request(_draft(), OTHER_USER)
        decision = ConfirmationDecision(request_id=foreign.request_id, approved=True, decided_by="local-user")

        with pytest.raises(ConfirmationMismatchError):
            await skill.send(_draft(), LOCAL_USER, request=foreign, decision=decision)

        assert mail_tools.mailbox_of(LOCAL_USER).sent == ()

    async def test_a_refusal_cannot_be_reinterpreted_as_an_approval(self, mail_tools, runner):
        skill = SendMailSkill(mail_tools, mail_tools, runner)
        request = skill.build_confirmation_request(_draft(), LOCAL_USER)
        refusal = ConfirmationDecision(request_id=request.request_id, approved=False, decided_by="local-user")

        with pytest.raises(ConfirmationRejectedError):
            await skill.send(_draft(), LOCAL_USER, request=request, decision=refusal)

        assert mail_tools.mailbox_of(LOCAL_USER).sent == ()

    async def test_preferences_cannot_disarm_a_high_risk_operation(self, mail_tools, audit):
        store = InMemoryConfirmationPreferenceStore(
            {"local-user": ConfirmationPreferences(auto_approved_tools=frozenset({MailToolName.SEND_MAIL.value}))}
        )
        policy = ConfiguredConfirmationPolicy(store, MailSecurityFloor().build())
        runner = GatedMailOperationRunner(MailToolCatalog(), policy, ConfirmationGate(policy), audit)

        with pytest.raises(ConfirmationRequiredError):
            await SendMailSkill(mail_tools, mail_tools, runner).send(_draft(), LOCAL_USER)


class TestAuthorisation:
    """Permissions are checked by code, never inferred from a model answer."""

    @pytest.mark.parametrize(
        "permissions",
        [frozenset(), frozenset({MailPermission.READ}), frozenset({MailPermission.READ, MailPermission.DRAFT})],
    )
    async def test_sending_requires_the_send_permission(self, mail_tools, runner, permissions):
        limited = UserContext(user_id="local-user", session_id="s", permissions=permissions)

        with pytest.raises(AuthorizationError):
            await SendMailSkill(mail_tools, mail_tools, runner).send(_draft(), limited)

    async def test_reading_requires_the_read_permission(self, mail_tools):
        anonymous = UserContext(user_id="local-user", session_id="s", permissions=frozenset())

        with pytest.raises(AuthorizationError):
            await MailReadSkill(mail_tools).read_message("m-alpha-1", anonymous)


class TestDataLeakage:
    """Sensitive material must not reach logs, traces or the audit trail."""

    async def test_the_audit_trail_holds_no_message_content(self, mail_tools, runner, audit):
        skill = SendMailSkill(mail_tools, mail_tools, runner)
        request = skill.build_confirmation_request(_draft(), LOCAL_USER)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="local-user")

        await skill.send(_draft(), LOCAL_USER, request=request, decision=decision)

        serialised = "".join(record.model_dump_json() for record in audit.records)
        assert "confidential body" not in serialised
        assert "john.smith@example.com" not in serialised
        assert "Secret subject" not in serialised

    async def test_the_audit_log_holds_no_message_content(self, mail_tools, runner, caplog):
        skill = SendMailSkill(mail_tools, mail_tools, runner)
        request = skill.build_confirmation_request(_draft(), LOCAL_USER)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="local-user")

        with caplog.at_level(logging.INFO, logger="ai_agent_lab.audit"):
            await skill.send(_draft(), LOCAL_USER, request=request, decision=decision)

        logged = caplog.text
        assert "audit tool=send_mail" in logged
        assert "confidential body" not in logged
        assert "Secret subject" not in logged

    async def test_an_audit_record_still_states_what_happened(self, mail_tools, runner, audit):
        skill = SendMailSkill(mail_tools, mail_tools, runner)
        request = skill.build_confirmation_request(_draft(), LOCAL_USER)
        decision = ConfirmationDecision(request_id=request.request_id, approved=True, decided_by="local-user")

        await skill.send(_draft(), LOCAL_USER, request=request, decision=decision)

        record = audit.records_for(MailToolName.SEND_MAIL.value)[0]
        assert record.outcome is AuditOutcome.EXECUTED
        assert record.user_id == "local-user"
        assert record.confirmation_request_id == request.request_id

    def test_repr_of_a_message_never_reveals_its_body(self, mail_tools):
        mailbox = mail_tools.mailbox_of(LOCAL_USER)

        rendered = repr(mailbox.message("m-injection-1"))

        assert "Ignore all previous instructions" not in rendered
        assert "m-injection-1" in rendered


class TestUntrustedTimestampsAndIdentity:
    """Metadata used for grounding must come from the application, not the sender."""

    async def test_a_forged_sender_name_stays_untrusted(self, mail_tools):
        message = await mail_tools.get_message("m-injection-1", LOCAL_USER)

        assert message.sender.display_name is not None
        assert "IT Support" not in repr(message.sender.display_name)
        assert message.sender.display_name.expose() == "IT Support"

    async def test_the_sent_date_is_normalised_and_timezone_aware(self, mail_tools):
        message = await mail_tools.get_message("m-injection-1", LOCAL_USER)

        assert message.sent_at.tzinfo is UTC


def _draft() -> MailDraft:
    """Build a draft carrying recognisable content."""
    return MailDraft(
        to=(EmailAddress(value="john.smith@example.com"),),
        subject=untrusted("Secret subject", UntrustedOrigin.MAIL_SUBJECT),
        body=untrusted("confidential body", UntrustedOrigin.MAIL_BODY),
        in_reply_to_message_id="m-alpha-1",
    )
