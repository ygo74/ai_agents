"""Tests of what this laboratory still owns around the authenticated caller.

The caller itself - how an authentication context becomes an
:class:`AgentPrincipal`, and the refusals that guard it - moved to
``ygo74-agent-runtime`` and is tested there. Two things stayed, and both are
tested here.

The first is the join between a principal and the permissions this deployment
grants it: what a role is worth is our decision, not the identity provider's and
not the runtime's either. That is precisely why it is no longer a method of the
principal.

The second is the credential. A token must never be readable by accident, because
a token in a log is a token in an incident report.
"""

from __future__ import annotations

import pytest
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal

from ai_agent_lab.core.security.tokens import AccessToken
from ai_agent_lab.core.security.user_contexts import UserContextFactory
from ai_agent_lab.mail.domain.permissions import MailPermission

# A fabricated string that merely looks like a token, so the redaction tests can
# assert it never appears in a representation.
SECRET = "ey.this-is-a-token-value"  # noqa: S105

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


@pytest.mark.security
class TestAccessTokenStaysSecret:
    """A credential must survive careless logging."""

    def test_its_representation_hides_the_value(self):
        token = AccessToken(SECRET, audience="mail-mcp")

        assert SECRET not in repr(token)
        assert SECRET not in str(token)
        assert SECRET not in f"token={token}"

    def test_the_representation_still_identifies_the_audience(self):
        """Redaction must not make an operator blind to what failed."""
        assert "mail-mcp" in repr(AccessToken(SECRET, audience="mail-mcp"))

    def test_the_value_is_reachable_only_through_an_explicit_call(self):
        assert AccessToken(SECRET).expose() == SECRET

    def test_an_empty_credential_is_refused(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            AccessToken("")
