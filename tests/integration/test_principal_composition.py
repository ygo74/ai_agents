"""Tests of who the agent is assembled for.

Serving several people from one process makes the caller a *parameter* of the
build rather than a setting of the deployment. What matters is that the identity
supplied at the boundary is the one every part of the runtime then acts on: the
mailbox that is read, the preferences that are applied, the owner excluded from a
reply, and the ledger a confirmation is recorded in.

The command line has no such boundary, so the configured local user must keep
working unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.maf_fakes import ScriptedChatClient, says

from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationPreferences,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.config.local_principal import LocalPrincipalSource
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner
from ai_agent_lab.mail.security_floor import MailSecurityFloor
from ai_agent_lab.mail.skills.analysis import MailReplyOutput

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# The deterministic dataset partitions mailboxes by owner, so a principal only
# finds mail when its subject is the owner of one. That is the property itself:
# `other-user` owns a separate mailbox the local user must never see.
DATASET_OWNER = "local-user"
DATASET_OWNER_EMAIL = "local-user@example.com"

REPLY_ANSWER = {
    "subject": "Re: Project Alpha - architecture review",
    "body": "Thanks. I will review the architecture document tomorrow.",
}

ADA = Principal(
    subject="ada-3f9a",
    email="ada@example.com",
    display_name="Ada Lovelace",
    roles=frozenset({"mail-user"}),
)


def build_for(principal: Principal | None, *, reasoner: ScriptedTextReasoner | None = None):
    """Assemble the agent for a caller, against the deterministic dataset."""
    return MailAgentCompositionRoot(
        MailAgentSettings(),
        ScriptedChatClient([says("nothing to do")]),
        principal=principal,
        reasoner=reasoner or ScriptedTextReasoner({}),
        base_path=REPOSITORY_ROOT,
    ).build(session_id="session-1")


async def reply_recipients(principal: Principal) -> set[str]:
    """Draft a reply-all to a message of the dataset and return its addressees."""
    runtime = build_for(principal, reasoner=ScriptedTextReasoner({MailReplyOutput: REPLY_ANSWER}))

    draft = await runtime.skills.reply.draft_reply_to_message(
        "m-alpha-3", "Confirm the retention policy", runtime.user, reply_all=True
    )

    return {address.value for address in (*draft.to, *draft.cc)}


class TestTheAgentActsForTheSuppliedCaller:
    """An authenticated caller replaces what used to be read from `.env`."""

    def test_the_subject_is_who_operations_are_attributed_to(self):
        runtime = build_for(ADA)

        assert runtime.user.user_id == ADA.subject
        assert runtime.principal == ADA

    def test_the_session_identifier_is_carried_into_the_context(self):
        assert build_for(ADA).user.session_id == "session-1"

    def test_permissions_are_granted_by_the_application(self):
        """A role asserted by an identity provider is a claim, not a grant."""
        assert build_for(ADA).user.permissions == MailPermission.declared()

    async def test_the_reply_excludes_the_mailbox_of_that_caller(self):
        """The owner address drives reply recipients, so it must follow the caller.

        `m-alpha-3` is addressed to the owner and to John. Replying to all must
        write to John and never back to the owner.
        """
        owner = Principal(subject=DATASET_OWNER, email=DATASET_OWNER_EMAIL)

        recipients = await reply_recipients(owner)

        assert DATASET_OWNER_EMAIL not in recipients
        assert "john.smith@example.com" in recipients

    async def test_the_owner_address_comes_from_the_caller_not_the_deployment(self):
        """This is what tells the two sources apart.

        The subject still owns the dataset mailbox, so the same message is read,
        but the caller authenticated with a different address. Only the caller's
        address may be treated as "the owner": if the deployment's
        `MAIL_AGENT_USER_EMAIL` were used instead, the configured address would
        be excluded here, and one person's reply would be shaped by another's
        configuration.
        """
        impersonated = Principal(subject=DATASET_OWNER, email="ada@example.com")

        recipients = await reply_recipients(impersonated)

        assert DATASET_OWNER_EMAIL in recipients


class TestTheCommandLineKeepsItsConfiguredUser:
    """One person, one machine, one mailbox: `.env` still describes the caller."""

    def test_omitting_a_caller_falls_back_to_the_configured_one(self):
        settings = MailAgentSettings()

        runtime = build_for(None)

        assert runtime.principal.subject == settings.user_id
        assert runtime.principal.email == settings.user_email

    def test_the_local_source_describes_the_configured_user(self):
        settings = MailAgentSettings()

        principal = LocalPrincipalSource(settings).principal()

        assert principal.subject == settings.user_id
        assert principal.email == settings.user_email


@pytest.mark.security
class TestCallersAreNotConfused:
    """Two callers must never share the state that belongs to one of them."""

    def test_two_callers_produce_two_unrelated_runtimes(self):
        other = Principal(subject="bob-77c1", email="bob@example.com")

        ada = build_for(ADA)
        bob = build_for(other)

        assert ada.user.user_id != bob.user.user_id
        assert ada.confirmation_ledger is not bob.confirmation_ledger

    def test_a_preference_recorded_for_one_caller_never_applies_to_another(self):
        """Preferences are keyed by subject, which is what keeps them apart.

        Note what this does *not* claim. The preferences currently come from
        `.env`, so they describe the deployment and are applied to whoever the
        principal happens to be. Serving several people will require a real
        per-user store; the property pinned here is that the lookup is already
        keyed by subject, so such a store cannot leak one caller's answer to
        another.
        """
        store = InMemoryConfirmationPreferenceStore(
            {ADA.subject: ConfirmationPreferences(auto_approved_tools=frozenset({"archive_mail"}))}
        )
        policy = ConfiguredConfirmationPolicy(store, MailSecurityFloor().build())
        archive = build_for(ADA).registry.skill("archive_mail").operation

        ada_context = ADA.to_user_context(session_id="s", permissions=MailPermission.declared())
        bob_context = Principal(subject="bob-77c1", email="bob@example.com").to_user_context(
            session_id="s", permissions=MailPermission.declared()
        )

        assert not policy.requires_confirmation(archive, ada_context)
        assert policy.requires_confirmation(archive, bob_context)
