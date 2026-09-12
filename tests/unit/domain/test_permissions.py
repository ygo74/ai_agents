"""Tests of the permission model.

Permissions are declared by the domain that owns them. What matters here is that
a second domain can be added without touching the first, and that configuration
naming a permission in text can never invent one.
"""

from __future__ import annotations

import pytest
from ygo74.agent_runtime.domains.security.permissions import (
    Permission,
    PermissionRegistry,
    UnknownPermissionError,
)

from ai_agent_lab.mail.domain.permissions import MailPermission


class TestPermission:
    """A permission is a namespaced value, not a member of a central list."""

    def test_it_renders_as_domain_and_action(self):
        assert MailPermission.SEND.value == "mail:send"
        assert str(MailPermission.SEND) == "mail:send"

    def test_two_declarations_of_the_same_permission_are_equal(self):
        assert Permission("mail", "read") == MailPermission.READ
        assert len({Permission("mail", "read"), MailPermission.READ}) == 1

    def test_permissions_of_two_domains_never_collide(self):
        assert Permission("jira", "read") != MailPermission.READ

    @pytest.mark.parametrize(("domain", "action"), [("", "read"), ("mail", ""), ("ma:il", "read")])
    def test_a_malformed_permission_is_refused(self, domain, action):
        with pytest.raises(ValueError, match="invalid permission part"):
            Permission(domain, action)


class TestMailDeclaration:
    """The mail domain owns its own permissions."""

    def test_it_declares_the_four_mail_capabilities(self):
        assert MailPermission.declared() == {
            MailPermission.READ,
            MailPermission.DRAFT,
            MailPermission.SEND,
            MailPermission.MANAGE,
        }

    def test_every_declared_permission_belongs_to_the_mail_domain(self):
        assert all(permission.domain == "mail" for permission in MailPermission.declared())


class TestPermissionRegistry:
    """Configuration names permissions in text; the registry resolves them."""

    def test_it_resolves_a_declared_permission(self):
        registry = PermissionRegistry(MailPermission.declared())

        assert registry.resolve("mail:send") is MailPermission.SEND

    def test_it_refuses_a_permission_no_domain_declared(self):
        registry = PermissionRegistry(MailPermission.declared())

        with pytest.raises(UnknownPermissionError, match="mail:delete"):
            registry.resolve("mail:delete")

    def test_a_second_domain_extends_it_without_touching_the_first(self):
        jira = frozenset({Permission("jira", "read")})

        registry = PermissionRegistry(MailPermission.declared() | jira)

        assert registry.resolve("jira:read").domain == "jira"
        assert registry.resolve("mail:read") is MailPermission.READ

    def test_it_reports_what_it_knows(self):
        registry = PermissionRegistry(MailPermission.declared())

        assert registry.declared() == MailPermission.declared()
