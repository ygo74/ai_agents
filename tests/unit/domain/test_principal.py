"""Tests of what this laboratory still owns around the authenticated caller.

Nearly everything about the caller moved to ``ygo74-agent-runtime`` and is tested
there: how an authentication context becomes an :class:`AgentPrincipal`, the
refusals that guard it, and the credentials that establish it.

One thing stayed, and it stayed on purpose. Joining a principal to the
permissions a deployment grants it is not the identity's business: what a role is
worth is our decision, not the identity provider's and not the library's either.
That is exactly why it is no longer a method of the principal, and why the join
is tested here rather than upstream.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal

from ai_agent_lab.core.security.user_contexts import UserContextFactory
from ai_agent_lab.mail.domain.permissions import MailPermission

ADA = AgentPrincipal(subject="3f9a-user", email="ada@example.com", display_name="Ada Lovelace")


class TestUserContextFactory:
    """The principal is what every operation of a session is attributed to."""

    def test_the_subject_becomes_the_user_the_operation_acts_for(self):
        context = UserContextFactory().for_principal(
            ADA,
            session_id="conv-1",
            permissions=MailPermission.declared(),
        )

        assert context.user_id == "3f9a-user"
        assert context.session_id == "conv-1"

    def test_permissions_are_granted_by_the_application_not_by_the_token(self):
        """Roles are claims about a caller; what they grant is our decision."""
        admin = AgentPrincipal(subject="3f9a-user", email="ada@example.com", roles=frozenset({"admin"}))

        context = UserContextFactory().for_principal(
            admin,
            session_id="conv-1",
            permissions=frozenset({MailPermission.READ}),
        )

        assert context.has_permission(MailPermission.READ)
        assert not context.has_permission(MailPermission.SEND)

    def test_two_agents_may_grant_the_same_caller_differently(self):
        """Which is why the grant is not a method of the principal."""
        factory = UserContextFactory()

        reader = factory.for_principal(ADA, session_id="s", permissions=frozenset({MailPermission.READ}))
        writer = factory.for_principal(ADA, session_id="s", permissions=MailPermission.declared())

        assert not reader.has_permission(MailPermission.SEND)
        assert writer.has_permission(MailPermission.SEND)
