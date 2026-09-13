"""Tests of the HTTP surface a mail MCP server can be given.

Over stdio this server's security rests on the operating system: a child process,
a pipe, no port. Over HTTP that argument is gone and only the token is left, so
these tests exist to make sure the token cannot quietly stop being checked.

The first two would pass if the authentication were deleted, were it not for the
third and fourth. Read them together.
"""

from __future__ import annotations

import pytest

from mail_mcp.protocol.http_surface import (
    HEALTH_PATH,
    TOKEN_VARIABLE,
    MissingServerTokenError,
    authenticated,
    authenticating,
    presented_token,
    required_token,
)
from mail_mcp.protocol.serving import LOOPBACK, Mailbox, MailToolSurface

SECRET = "a-shared-deployment-secret"  # noqa: S105 - a fixture, not a credential

pytestmark = pytest.mark.security


class _EmptyDirectory:
    """A mailbox directory for tests that never reach a mailbox.

    These tests stop at the guard or at the transport, so resolving an owner
    would mean the test failed to test what it claims to.
    """

    def resolve(self, owner: str) -> Mailbox:
        raise AssertionError(f"no call should reach a mailbox, but {owner!r} was resolved")


class TestItRefusesToServeWithoutATokenToCheck:
    """Failing to boot is cheap; a mailbox on an open port is not."""

    def test_an_absent_token_stops_the_server(self):
        with pytest.raises(MissingServerTokenError):
            required_token({})

    def test_a_blank_token_is_not_a_token(self):
        with pytest.raises(MissingServerTokenError):
            required_token({TOKEN_VARIABLE: "   "})

    def test_the_refusal_says_why_it_matters(self):
        """An operator reading this must not think it is a formality."""
        with pytest.raises(MissingServerTokenError) as refusal:
            required_token({})

        assert TOKEN_VARIABLE in str(refusal.value)
        assert "mailbox" in str(refusal.value)

    def test_a_configured_token_is_returned_trimmed(self):
        assert required_token({TOKEN_VARIABLE: f"  {SECRET}  "}) == SECRET


class TestItReadsWhatACallerPresented:
    """Both shapes are accepted; neither is guessed at."""

    @pytest.mark.parametrize(
        "header",
        [f"Bearer {SECRET}", f"bearer {SECRET}", f"BEARER {SECRET}", SECRET, f"  Bearer {SECRET}  "],
    )
    def test_a_credential_is_recognised_however_it_is_written(self, header):
        assert presented_token(header) == SECRET

    @pytest.mark.parametrize("header", [None, "", "   "])
    def test_no_header_presents_nothing(self, header):
        assert presented_token(header) == ""


class TestItRefusesACallerThatCannotProveItself:
    """The control itself. If these pass with the check removed, they are useless."""

    def test_the_right_credential_is_accepted(self):
        assert authenticated(f"Bearer {SECRET}", SECRET)

    @pytest.mark.parametrize(
        "header",
        [None, "", "Bearer ", "Bearer wrong-secret", "wrong-secret", f"Basic {SECRET}"],
    )
    def test_anything_else_is_refused(self, header):
        assert not authenticated(header, SECRET)

    def test_a_prefix_of_the_secret_is_refused(self):
        """Comparison is whole-value, not a starts-with."""
        assert not authenticated(f"Bearer {SECRET[:-1]}", SECRET)

    def test_the_secret_with_something_appended_is_refused(self):
        assert not authenticated(f"Bearer {SECRET}x", SECRET)


class TestTheHealthProbeStaysOpen:
    """An orchestrator must be able to ask whether the process is alive."""

    def test_the_probe_has_a_stable_path(self):
        assert HEALTH_PATH == "/healthz"


class TestAHeaderWeCannotEvenRepresent:
    """A refusal, never a traceback.

    Starlette decodes header bytes as latin-1, so a caller may present any byte
    at all. ``hmac.compare_digest`` raises ``TypeError`` on non-ASCII ``str``,
    and an unauthenticated caller able to raise inside the process holding the
    Google credential is a log-flood vector on the one surface meant to be hard.
    """

    @pytest.mark.parametrize("header", ["Bearer caf\xe9", "\xff\xfe", "Bearer \U0001f512"])
    def test_a_non_ascii_credential_is_refused_rather_than_raising(self, header):
        assert not authenticated(header, SECRET)


class TestTheWrappedApplication:
    """The guard as a caller meets it, rather than as a function.

    Every test above would still pass if ``authenticating`` forgot to install
    the middleware. These drive the real ASGI application instead.
    """

    @staticmethod
    def _client(host: str = LOOPBACK):
        from starlette.testclient import TestClient

        surface = MailToolSurface(_EmptyDirectory(), name="test-surface", host=host, port=9100)
        return TestClient(authenticating(surface.server.streamable_http_app(), SECRET))

    def test_the_probe_answers_without_a_credential(self):
        with self._client() as client:
            response = client.get(HEALTH_PATH)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_a_call_without_a_credential_is_refused(self):
        with self._client() as client:
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        assert response.status_code == 401

    def test_a_call_with_the_wrong_credential_is_refused(self):
        with self._client() as client:
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": "Bearer not-the-secret"},
            )

        assert response.status_code == 401

    def test_a_credentialled_call_from_another_host_is_not_rejected_as_misdirected(self):
        """The bug this test exists for.

        ``FastMCP`` freezes its DNS-rebinding allow-list to loopback when it is
        built with the default bind address, and never revisits it. A server
        bound for a container would then answer every real request - which
        arrives with a service name in ``Host`` - with 421, after passing
        authentication and before reaching a tool. The health probe would still
        be green, so nothing would say why.
        """
        with self._client(host="0.0.0.0") as client:  # noqa: S104 - what a container binds
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={
                    "Authorization": f"Bearer {SECRET}",
                    "Host": "mail-mcp-gmail:9100",
                    "Accept": "application/json, text/event-stream",
                },
            )

        assert response.status_code != 421

    def test_a_loopback_bind_keeps_the_rebinding_protection(self):
        """Turning the protection off is a consequence of the bind, not a habit."""
        surface = MailToolSurface(_EmptyDirectory(), name="test-surface", host=LOOPBACK, port=9100)

        assert surface.server.settings.transport_security is not None
