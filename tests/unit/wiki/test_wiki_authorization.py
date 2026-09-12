"""Tests of how a caller identifies itself to a remote wiki MCP server.

This is the mechanism that makes an agent act *on behalf of* a person rather than
as a shared service account. It is also the mechanism that leaks a credential if
it is written carelessly, so both properties are pinned here.
"""

from __future__ import annotations

from base64 import b64decode

import pytest
from pydantic import SecretStr
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.auth import WikiAuthScheme
from ai_agent_lab.wiki.mcp.authorization import (
    AUTHORIZATION,
    ConfiguredUserCredentials,
    WikiAuthorization,
    WikiAuthorizationError,
    authorization_for,
)
from ai_agent_lab.wiki.mcp.binding import McpServerBinding, McpTransport
from ai_agent_lab.wiki.mcp.connection import McpConnection
from ai_agent_lab.wiki.wiki_errors import WikiAccessDeniedError

# A fake credential, present so the tests can assert it never escapes into a
# representation, a log line or an error message.
SECRET = "s3cret-token-value"  # noqa: S105
ALL_TOOLS = {name.value: name.value for name in WikiToolName}


def user(user_id: str = "diana") -> UserContext:
    """Build a caller."""
    return UserContext(user_id=user_id, session_id="s")


def authorization(scheme: WikiAuthScheme, *, account: str = "diana@example.com") -> WikiAuthorization:
    """Build the authorisation of one configured user."""
    return authorization_for(
        scheme,
        user_id="diana",
        account=account,
        secret=SecretStr(SECRET),
    )


class TestHeaderFormats:
    """The three formats `sooperset/mcp-atlassian` accepts, verbatim."""

    def test_basic_carries_the_email_and_token(self):
        """Confluence Cloud: `Basic <base64(email:api_token)>`."""
        headers = authorization(WikiAuthScheme.BASIC).headers_for(user())

        value = headers[AUTHORIZATION]
        assert value.startswith("Basic ")
        assert b64decode(value.removeprefix("Basic ")).decode() == f"diana@example.com:{SECRET}"

    def test_token_carries_a_personal_access_token(self):
        """Confluence Data Center: `Token <PAT>`."""
        headers = authorization(WikiAuthScheme.TOKEN).headers_for(user())

        assert headers[AUTHORIZATION] == f"Token {SECRET}"

    def test_bearer_carries_an_oauth_token(self):
        headers = authorization(WikiAuthScheme.BEARER).headers_for(user())

        assert headers[AUTHORIZATION] == f"Bearer {SECRET}"

    def test_no_scheme_sends_no_header(self):
        """Over stdio there is no per-request identity to send."""
        assert WikiAuthorization().headers_for(user()) == {}


class TestPerUserIdentity:
    """Whether the transport tells the server who is asking."""

    def test_a_scheme_makes_a_connection_per_user(self):
        assert authorization(WikiAuthScheme.TOKEN).is_per_user

    def test_no_scheme_means_one_identity_for_everybody(self):
        assert not WikiAuthorization().is_per_user

    @pytest.mark.security
    def test_a_caller_with_no_credential_is_refused(self):
        """Falling back to a shared account would grant a view they lack."""
        built = authorization(WikiAuthScheme.TOKEN)

        with pytest.raises(WikiAccessDeniedError, match="no wiki credential"):
            built.headers_for(user("somebody-else"))

    @pytest.mark.security
    def test_one_caller_never_receives_another_caller_credential(self):
        credentials = ConfiguredUserCredentials(
            {
                "diana": ("diana@example.com", SecretStr("diana-token")),
                "alice": ("alice@example.com", SecretStr("alice-token")),
            }
        )
        built = WikiAuthorization(WikiAuthScheme.TOKEN, credentials)

        assert built.headers_for(user("diana"))[AUTHORIZATION] == "Token diana-token"
        assert built.headers_for(user("alice"))[AUTHORIZATION] == "Token alice-token"


class TestConfigurationRefusals:
    """A scheme that cannot be honoured fails at assembly, not at the first call."""

    def test_a_scheme_without_a_credential_is_refused(self):
        with pytest.raises(WikiAuthorizationError, match="WIKI_MCP_USER_SECRET"):
            authorization_for(
                WikiAuthScheme.TOKEN,
                user_id="diana",
                account="",
                secret=SecretStr(""),
            )

    def test_basic_without_an_account_is_refused(self):
        """`Basic` encodes an email and a token; one of them is not optional."""
        with pytest.raises(WikiAuthorizationError, match="WIKI_MCP_USER_ACCOUNT"):
            authorization_for(
                WikiAuthScheme.BASIC,
                user_id="diana",
                account="",
                secret=SecretStr(SECRET),
            )

    def test_a_scheme_declared_without_credentials_is_refused(self):
        with pytest.raises(ValueError, match="needs a source of user credentials"):
            WikiAuthorization(WikiAuthScheme.TOKEN)


@pytest.mark.security
class TestSecretHandling:
    """A credential must not reach a log, a trace or an error message."""

    def test_the_authorisation_never_reveals_a_credential(self):
        built = authorization(WikiAuthScheme.TOKEN)

        assert SECRET not in repr(built)
        assert SECRET not in str(built)

    def test_the_credential_store_never_reveals_a_credential(self):
        credentials = ConfiguredUserCredentials({"diana": ("diana@example.com", SecretStr(SECRET))})

        assert SECRET not in repr(credentials.for_user(user()))

    def test_the_connection_never_reveals_the_header(self):
        """A connection is logged when a transport fails; the header is not."""
        binding = McpServerBinding(
            server="mcp-atlassian",
            transport=McpTransport.HTTP,
            capabilities=(WikiToolName.GET_PAGE,),
            tools=ALL_TOOLS,
            url="https://wiki-mcp.internal/mcp",
        )

        connection = McpConnection(
            binding,
            headers=authorization(WikiAuthScheme.TOKEN).headers_for(user()),
        )

        assert SECRET not in repr(connection)

    def test_a_refusal_names_the_user_not_the_credential(self):
        built = authorization(WikiAuthScheme.TOKEN)

        with pytest.raises(WikiAccessDeniedError) as failure:
            built.headers_for(user("mallory"))

        assert "mallory" in str(failure.value)
        assert SECRET not in str(failure.value)
