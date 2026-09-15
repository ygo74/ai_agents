"""Tests of how the two MCP servers of this repository decide who may call them.

The schemes, the environment mapping and the guard all live in the runtime and are
tested there. Repeating any of it here would recreate exactly the copy-per-server
problem that moving them was meant to end.

What is this repository's to get right is the wiring: which prefix each server
reads, who its shared secret stands for, and the fact that both servers really do
share one answer rather than two that could drift apart.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from ygo74.agent_runtime.domains.auth.auth_errors import AuthenticationError
from ygo74.agent_runtime.domains.auth.authentication_policy import (
    AuthenticationConfigurationError,
    AuthenticationMode,
)

from mail_mcp.protocol import authentication as mail_auth
from wiki_mcp.protocol import authentication as wiki_auth

MAIL_SECRET = "the-mail-deployment-secret"  # noqa: S105 - a fixture, not a credential
WIKI_SECRET = "the-wiki-deployment-secret"  # noqa: S105 - a fixture, not a credential

pytestmark = pytest.mark.security

SERVERS = [
    pytest.param(mail_auth.MailMcpAuthentication, "MAIL_MCP_", "mail-agent", id="mail"),
    pytest.param(wiki_auth.WikiMcpAuthentication, "WIKI_MCP_", "wiki-agent", id="wiki"),
]


class TestBothServersRefuseSilence:
    """The property that must hold for every server in this repository.

    Each of these processes holds a credential for the system behind it. A server
    that started without being told who may call it would put that system on an open
    port, and the only sign of it would be the absence of a line in a log.
    """

    @pytest.mark.parametrize(("reader", "prefix", "caller"), SERVERS)
    def test_a_server_told_nothing_refuses_to_serve(self, reader, prefix, caller):
        with pytest.raises(AuthenticationConfigurationError, match=f"{prefix}AUTH_MODE"):
            reader.from_environment({})

    @pytest.mark.parametrize(("reader", "prefix", "caller"), SERVERS)
    def test_anonymous_has_to_be_written_down(self, reader, prefix, caller):
        authentication = reader.from_environment({f"{prefix}AUTH_MODE": "none"})

        assert authentication.policy.mode is AuthenticationMode.NONE


class TestEachServerReadsItsOwnVariables:
    """Two servers in one deployment, each with its own secret."""

    ENVIRONMENT: ClassVar[dict[str, str]] = {
        "MAIL_MCP_AUTH_MODE": "api_key",
        "MAIL_MCP_HTTP_TOKEN": MAIL_SECRET,
        "WIKI_MCP_AUTH_MODE": "api_key",
        "WIKI_MCP_HTTP_TOKEN": WIKI_SECRET,
    }

    @pytest.mark.parametrize(("reader", "prefix", "caller"), SERVERS)
    def test_the_caller_is_named_after_the_agent_deployed_with_it(self, reader, prefix, caller):
        secret = self.ENVIRONMENT[f"{prefix}HTTP_TOKEN"]

        context = reader.from_environment(self.ENVIRONMENT).policy.build().authenticate(
            {"authorization": f"Bearer {secret}"}
        )

        assert context is not None
        assert context.identity.user_id == caller

    def test_the_mail_secret_does_not_open_the_wiki_server(self):
        """Two servers, two secrets: neither is a key to the other."""
        wiki = wiki_auth.WikiMcpAuthentication.from_environment(self.ENVIRONMENT)

        with pytest.raises(AuthenticationError):
            wiki.policy.build().authenticate({"authorization": f"Bearer {MAIL_SECRET}"})

    def test_the_wiki_secret_does_not_open_the_mail_server(self):
        mail = mail_auth.MailMcpAuthentication.from_environment(self.ENVIRONMENT)

        with pytest.raises(AuthenticationError):
            mail.policy.build().authenticate({"authorization": f"Bearer {WIKI_SECRET}"})


class TestTheDeployedBindingStillWorks:
    """`config/mcp/gmail-http.yaml` and the running container expect exactly this.

    The agent presents `Authorization: Bearer <secret>`. A change that broke it
    would break a deployment rather than a test, so it is pinned here.
    """

    def _chain(self):
        return mail_auth.MailMcpAuthentication.from_environment(
            {"MAIL_MCP_HTTP_TOKEN": MAIL_SECRET}
        ).policy.build()

    def test_a_token_alone_still_configures_the_server(self):
        """No MAIL_MCP_AUTH_MODE in the deployed compose file, and none needed."""
        assert self._chain().authenticate({"authorization": f"Bearer {MAIL_SECRET}"}) is not None

    def test_the_header_is_the_one_the_agent_sends(self):
        assert self._chain().authenticate({"authorization": f"Bearer {MAIL_SECRET}"}) is not None

    def test_anything_else_is_refused(self):
        for header in ({}, {"authorization": "Bearer wrong"}, {"x-api-key": MAIL_SECRET}):
            with pytest.raises(AuthenticationError):
                self._chain().authenticate(header)


class TestTheTwoServersShareOneAnswer:
    """The point of the whole exercise.

    If these ever stop being the same object, two servers in one repository have
    started answering "who may call me" differently - which is how a weaker answer
    appears without anybody deciding it should.
    """

    def test_both_delegate_to_the_same_reader(self):
        from ygo74.agent_runtime.domains.mcpserver.settings import McpServerAuthentication

        mail = mail_auth.MailMcpAuthentication.from_environment({"MAIL_MCP_AUTH_MODE": "none"})
        wiki = wiki_auth.WikiMcpAuthentication.from_environment({"WIKI_MCP_AUTH_MODE": "none"})

        assert isinstance(mail, McpServerAuthentication)
        assert isinstance(wiki, McpServerAuthentication)

    def test_neither_module_carries_logic_of_its_own(self):
        """A guard on the shape, not the behaviour.

        These modules exist to name a prefix and a caller. The moment one grows a
        branch or a loop, it has an opinion the other does not share - and two
        opinions about who may call a server is one too many.
        """
        import ast
        import inspect

        branching = (ast.If, ast.For, ast.While, ast.Try, ast.IfExp, ast.Match)

        for module in (mail_auth, wiki_auth):
            tree = ast.parse(inspect.getsource(module))
            found = [type(node).__name__ for node in ast.walk(tree) if isinstance(node, branching)]

            assert not found, f"{module.__name__} grew a decision of its own: {found}"
