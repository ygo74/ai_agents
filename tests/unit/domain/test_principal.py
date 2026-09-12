"""Tests of the authenticated caller and of the credentials that establish it.

Two properties matter here, and both are security properties rather than
convenience. A principal must never be invented when authentication produced
nothing, because acting for "somebody" is how one mailbox answers for another.
And a credential must never be readable by accident, because a token in a log is
a token in an incident report.
"""

from __future__ import annotations

import pytest

from ai_agent_lab.core.security.principal import Principal, PrincipalError
from ai_agent_lab.core.security.tokens import AccessToken
from ai_agent_lab.mail.domain.permissions import MailPermission

# A fabricated string that merely looks like a token, so the redaction tests can
# assert it never appears in a representation.
SECRET = "ey.this-is-a-token-value"  # noqa: S105


def auth_context(**overrides: object) -> dict[str, object]:
    """Build the wire shape a serving library hands to an application."""
    identity: dict[str, object] = {
        "subject": "3f9a-user",
        "userId": "3f9a-user",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
    }
    identity.update(overrides.pop("identity", {}))  # type: ignore[arg-type]
    context: dict[str, object] = {
        "authType": "jwt",
        "userId": "3f9a-user",
        "identity": identity,
        "roles": ["mail-user"],
    }
    context.update(overrides)
    return context


class TestPrincipalFromAuthContext:
    """The caller is read from the transport, never from configuration."""

    def test_it_reads_the_subject_and_the_mailbox(self):
        principal = Principal.from_auth_context(auth_context())

        assert principal.subject == "3f9a-user"
        assert principal.email == "ada@example.com"
        assert principal.display_name == "Ada Lovelace"

    def test_it_keeps_the_roles_the_provider_asserted(self):
        principal = Principal.from_auth_context(auth_context(roles=["mail-user", "auditor"]))

        assert principal.has_role("auditor")
        assert not principal.has_role("admin")

    def test_it_falls_back_to_the_username_for_display(self):
        principal = Principal.from_auth_context(auth_context(identity={"name": None, "username": "ada"}))

        assert principal.display_name == "ada"

    def test_it_ignores_roles_that_are_not_text(self):
        """A wire payload is third-party data: it may contain anything."""
        principal = Principal.from_auth_context(auth_context(roles=["mail-user", 7, None, "  "]))

        assert principal.roles == frozenset({"mail-user"})

    def test_it_accepts_a_subject_carried_only_at_the_top_level(self):
        context = auth_context(identity={"subject": None, "userId": None})

        assert Principal.from_auth_context(context).subject == "3f9a-user"


@pytest.mark.security
class TestPrincipalRefusesToGuess:
    """An unauthenticated request is refused, never served as somebody."""

    @pytest.mark.parametrize("context", [None, {}])
    def test_an_absent_authentication_is_refused(self, context):
        with pytest.raises(PrincipalError, match="no authenticated caller"):
            Principal.from_auth_context(context)

    def test_a_caller_without_a_subject_is_refused(self):
        with pytest.raises(PrincipalError, match="no subject"):
            Principal.from_auth_context(auth_context(userId=None, identity={"subject": None, "userId": None}))

    def test_a_caller_without_a_mailbox_is_refused(self):
        """Serving a mailbox needs an address; defaulting one would pick a victim."""
        with pytest.raises(PrincipalError, match="no email"):
            Principal.from_auth_context(auth_context(identity={"email": None}))

    def test_a_principal_cannot_be_mutated_after_authentication(self):
        principal = Principal.from_auth_context(auth_context())

        with pytest.raises(ValueError):
            principal.subject = "somebody-else"  # type: ignore[misc]


class TestAnAgentThatDoesNotAddressByEmail:
    """Not every agent identifies its subject by an e-mail address.

    A wiki account is an account identifier on Cloud and a username on Data
    Center, and an identity provider may assert neither. Such an agent says so
    explicitly rather than being refused callers it can serve, and rather than
    inventing an address that would then appear in every audit record.
    """

    def test_a_caller_without_an_email_is_accepted(self):
        principal = Principal.from_auth_context(
            auth_context(identity={"email": None}),
            require_email=False,
        )

        assert principal.subject == "3f9a-user"
        assert principal.email == ""

    def test_an_address_is_still_kept_when_the_provider_asserts_one(self):
        principal = Principal.from_auth_context(auth_context(), require_email=False)

        assert principal.email == "ada@example.com"

    def test_the_subject_is_still_mandatory(self):
        """The subject is what state is partitioned by, so it is never optional."""
        with pytest.raises(PrincipalError, match="no subject"):
            Principal.from_auth_context(
                auth_context(userId=None, identity={"subject": None, "userId": None}),
                require_email=False,
            )

    def test_an_absent_authentication_is_still_refused(self):
        """Relaxing the address never relaxes the need for a caller."""
        with pytest.raises(PrincipalError, match="no authenticated caller"):
            Principal.from_auth_context(None, require_email=False)


class TestUserContext:
    """The principal is what every operation of a session is attributed to."""

    def test_the_subject_becomes_the_user_the_operation_acts_for(self):
        principal = Principal.from_auth_context(auth_context())

        context = principal.to_user_context(session_id="conv-1", permissions=MailPermission.declared())

        assert context.user_id == "3f9a-user"
        assert context.session_id == "conv-1"

    def test_permissions_are_granted_by_the_application_not_by_the_token(self):
        """Roles are claims about a caller; what they grant is our decision."""
        principal = Principal.from_auth_context(auth_context(roles=["admin"]))

        context = principal.to_user_context(session_id="conv-1", permissions=frozenset({MailPermission.READ}))

        assert context.has_permission(MailPermission.READ)
        assert not context.has_permission(MailPermission.SEND)


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
