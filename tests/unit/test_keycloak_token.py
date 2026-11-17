"""Tests for the developer command that obtains and inspects Keycloak tokens."""

# Fake credentials and token endpoint URLs below exercise secret handling; they
# are test-only values and must never be replaced with real credentials.
# ruff: noqa: S105, S106, S107

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from scripts import keycloak_token


class FakeOidcTransport(keycloak_token.OidcTransport):
    """Capture OIDC requests and return declared responses without networking."""

    def __init__(self, *responses: keycloak_token.OidcHttpResponse) -> None:
        """Store ordered responses for discovery and token requests."""
        self.responses = list(responses)
        self.get_calls: list[tuple[str, float]] = []
        self.post_calls: list[dict[str, Any]] = []

    def get(self, url: str, *, timeout: float) -> keycloak_token.OidcHttpResponse:
        """Capture the discovery request and return its next response."""
        self.get_calls.append((url, timeout))
        return self.responses.pop(0)

    def post_form(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        auth: tuple[str, str] | None,
        timeout: float,
    ) -> keycloak_token.OidcHttpResponse:
        """Capture the token request and return its next response."""
        self.post_calls.append({"url": url, "data": dict(data), "auth": auth, "timeout": timeout})
        return self.responses.pop(0)


def response(status_code: int, payload: object) -> keycloak_token.OidcHttpResponse:
    """Build one fake OIDC response."""
    return keycloak_token.OidcHttpResponse(status_code=status_code, payload=payload)


def discovery_payload(
    issuer: str = "https://identity.example/realms/agents",
    token_endpoint: str = "https://identity.example/realms/agents/protocol/openid-connect/token",
) -> dict[str, str]:
    """Return valid discovery metadata for a Keycloak realm."""
    return {"issuer": issuer, "token_endpoint": token_endpoint}


def encode_jwt_claims(claims: Mapping[str, object]) -> str:
    """Create a structurally valid JWT-shaped value without a real signature."""

    def encode(value: Mapping[str, object]) -> str:
        """Encode JSON as one unpadded URL-safe JWT segment."""
        raw = json.dumps(value).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode(claims)}.signature"


def test_public_client_uses_discovery_and_sends_password_grant() -> None:
    """Discover the endpoint and send public-client credentials as form data."""
    transport = FakeOidcTransport(
        response(200, discovery_payload()),
        response(200, {"access_token": "header.payload.signature", "token_type": "Bearer"}),
    )
    config = keycloak_token.TokenRequest(
        issuer_url="https://identity.example/realms/agents",
        client_id="inspector",
        username="alice",
        password="password-value",
        scope="openid profile",
        timeout=7.5,
    )

    access_token = keycloak_token.obtain_access_token(config, transport)

    assert access_token == "header.payload.signature"
    assert transport.get_calls == [
        ("https://identity.example/realms/agents/.well-known/openid-configuration", 7.5)
    ]
    assert transport.post_calls == [
        {
            "url": "https://identity.example/realms/agents/protocol/openid-connect/token",
            "data": {
                "grant_type": "password",
                "client_id": "inspector",
                "username": "alice",
                "password": "password-value",
                "scope": "openid profile",
            },
            "auth": None,
            "timeout": 7.5,
        }
    ]


def test_confidential_client_uses_http_basic_for_client_authentication() -> None:
    """Keep a supplied client secret out of the password-grant form."""
    transport = FakeOidcTransport(
        response(200, discovery_payload()),
        response(200, {"access_token": "access-token"}),
    )
    config = keycloak_token.TokenRequest(
        issuer_url="https://identity.example/realms/agents",
        client_id="confidential-client",
        username="alice",
        password="user-password",
        client_secret="client-secret",
    )

    keycloak_token.obtain_access_token(config, transport)

    assert transport.post_calls[0]["auth"] == ("confidential-client", "client-secret")
    assert "client_id" not in transport.post_calls[0]["data"]
    assert "client_secret" not in transport.post_calls[0]["data"]


@pytest.mark.parametrize(
    "issuer_url",
    ["http://identity.example/realm", "https:///realm", "https://user:pass@identity.example/realm"],
)
def test_invalid_issuer_is_rejected_before_network_access(issuer_url: str) -> None:
    """Reject non-HTTPS or credential-bearing issuer URLs before sending requests."""
    transport = FakeOidcTransport()
    config = keycloak_token.TokenRequest(
        issuer_url=issuer_url,
        client_id="inspector",
        username="alice",
        password="password-value",
    )

    with pytest.raises(keycloak_token.KeycloakTokenError, match="HTTPS issuer URL"):
        keycloak_token.obtain_access_token(config, transport)

    assert transport.get_calls == []


def test_discovery_issuer_must_match_and_token_endpoint_must_be_safe() -> None:
    """Reject metadata that redirects credentials to another or unsafe endpoint."""
    mismatched = FakeOidcTransport(response(200, discovery_payload(issuer="https://other.example/realm")))
    config = keycloak_token.TokenRequest(
        issuer_url="https://identity.example/realms/agents",
        client_id="inspector",
        username="alice",
        password="password-value",
    )

    with pytest.raises(keycloak_token.KeycloakTokenError, match="issuer does not match"):
        keycloak_token.obtain_access_token(config, mismatched)

    insecure_endpoint = FakeOidcTransport(
        response(200, discovery_payload(token_endpoint="http://identity.example/token"))
    )
    with pytest.raises(keycloak_token.KeycloakTokenError, match="token endpoint must be a safe HTTPS URL"):
        keycloak_token.obtain_access_token(config, insecure_endpoint)

    credential_endpoint = FakeOidcTransport(
        response(200, discovery_payload(token_endpoint="https://someone:secret@identity.example/token"))
    )
    with pytest.raises(keycloak_token.KeycloakTokenError, match="token endpoint must be a safe HTTPS URL"):
        keycloak_token.obtain_access_token(config, credential_endpoint)


@pytest.mark.parametrize(
    "discovery_response",
    [response(503, {"internal": "private server details"}), response(200, ["not", "an", "object"])],
)
def test_invalid_discovery_responses_fail_without_echoing_the_body(
    discovery_response: keycloak_token.OidcHttpResponse,
) -> None:
    """Reject status and payload errors without retaining discovery contents."""
    transport = FakeOidcTransport(discovery_response)
    config = keycloak_token.TokenRequest(
        issuer_url="https://identity.example/realms/agents",
        client_id="inspector",
        username="alice",
        password="password-value",
    )

    with pytest.raises(keycloak_token.KeycloakTokenError) as failure:
        keycloak_token.obtain_access_token(config, transport)

    assert "private server details" not in str(failure.value)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_non_positive_or_non_finite_timeout_is_rejected(timeout: float) -> None:
    """Require every network call to have a finite positive timeout."""
    transport = FakeOidcTransport()
    config = keycloak_token.TokenRequest(
        issuer_url="https://identity.example/realms/agents",
        client_id="inspector",
        username="alice",
        password="password-value",
        timeout=timeout,
    )

    with pytest.raises(keycloak_token.KeycloakTokenError, match="positive number"):
        keycloak_token.obtain_access_token(config, transport)

    assert transport.get_calls == []


def test_httpx_transport_verifies_tls_and_does_not_follow_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure verified TLS and prevent redirects from forwarding credentials."""
    state: dict[str, Any] = {}

    class FakeResponse:
        """Return one harmless discovery payload."""

        status_code = 200

        def json(self) -> dict[str, str]:
            """Return valid JSON content."""
            return {"issuer": "https://identity.example/realm"}

    class FakeClient:
        """Capture HTTP client policy and request arguments."""

        def __init__(self, **kwargs: Any) -> None:
            """Store client options for assertions."""
            state["client_options"] = kwargs

        def __enter__(self) -> FakeClient:
            """Open the fake client."""
            return self

        def __exit__(self, *_: object) -> None:
            """Close the fake client."""

        def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
            """Record the request and return the declared response."""
            state["request"] = (method, url, kwargs)
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    result = keycloak_token.HttpxOidcTransport().get(
        "https://identity.example/realm/.well-known/openid-configuration", timeout=4.0
    )

    assert result.status_code == 200
    assert state["client_options"] == {"verify": True, "timeout": 4.0, "follow_redirects": False}
    assert state["request"] == (
        "GET",
        "https://identity.example/realm/.well-known/openid-configuration",
        {"data": None, "auth": None},
    )


def test_discovery_and_grant_failures_do_not_expose_server_details_or_credentials() -> None:
    """Sanitize HTTP failures even when response bodies contain submitted secrets."""
    password = "private-user-password"
    secret = "private-client-secret"
    transport = FakeOidcTransport(
        response(200, discovery_payload()),
        response(400, {"error": "invalid_grant", "error_description": f"rejected {password} {secret}"}),
    )
    config = keycloak_token.TokenRequest(
        issuer_url="https://identity.example/realms/agents",
        client_id="inspector",
        username="alice",
        password=password,
        client_secret=secret,
    )

    with pytest.raises(keycloak_token.KeycloakTokenError) as failure:
        keycloak_token.obtain_access_token(config, transport)

    assert password not in str(failure.value)
    assert secret not in str(failure.value)
    assert "400" in str(failure.value)


def test_malformed_token_response_does_not_echo_response_body() -> None:
    """Reject token responses without an access token and keep body text private."""
    transport = FakeOidcTransport(
        response(200, discovery_payload()),
        response(200, {"error_description": "internal response with private details"}),
    )
    config = keycloak_token.TokenRequest(
        issuer_url="https://identity.example/realms/agents",
        client_id="inspector",
        username="alice",
        password="password-value",
    )

    with pytest.raises(keycloak_token.KeycloakTokenError, match="did not contain an access token") as failure:
        keycloak_token.obtain_access_token(config, transport)

    assert "private details" not in str(failure.value)


def test_jwt_claims_are_decoded_locally_without_signature_verification() -> None:
    """Decode the payload of a three-part JWT without validating its signature."""
    token = encode_jwt_claims({"sub": "user-123", "aud": ["mcp-agent"], "exp": 1_800_000_000})

    assert keycloak_token.decode_jwt_claims(token) == {
        "sub": "user-123",
        "aud": ["mcp-agent"],
        "exp": 1_800_000_000,
    }


@pytest.mark.parametrize("token", ["opaque-token", "header.encrypted-key.iv.ciphertext.tag", "a.!.c"])
def test_opaque_encrypted_and_malformed_tokens_have_no_decoded_claims(token: str) -> None:
    """Treat opaque, encrypted, and invalid claim payloads as unavailable."""
    assert keycloak_token.decode_jwt_claims(token) is None


def test_cli_prints_bearer_token_and_labels_claims_unverified(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Render the token for copying and decoded claims with a verification caveat."""
    access_token = encode_jwt_claims({"sub": "user-123"})
    transport = FakeOidcTransport(
        response(200, discovery_payload()),
        response(200, {"access_token": access_token}),
    )

    exit_code = keycloak_token.main(
        [
            "--issuer-url",
            "https://identity.example/realms/agents",
            "--client-id",
            "inspector",
            "--username",
            "alice",
            "--password",
            "password-value",
        ],
        transport=transport,
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert f"Bearer {access_token}" in captured.out
    assert '"sub": "user-123"' in captured.out
    assert "unverified" in captured.out.lower()
    assert captured.err == ""


def test_cli_reports_opaque_claims_without_hiding_the_token(capsys: pytest.CaptureFixture[str]) -> None:
    """Keep a usable opaque token visible and explain why claims are unavailable."""
    transport = FakeOidcTransport(
        response(200, discovery_payload()),
        response(200, {"access_token": "opaque-access-token"}),
    )

    exit_code = keycloak_token.main(
        [
            "--issuer-url",
            "https://identity.example/realms/agents",
            "--client-id",
            "inspector",
            "--username",
            "alice",
            "--password",
            "password-value",
        ],
        transport=transport,
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Bearer opaque-access-token" in captured.out
    assert "could not be decoded" in captured.out.lower()


def test_cli_sanitizes_transport_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """Never echo credentials embedded in a low-level transport exception."""

    class FailingTransport(FakeOidcTransport):
        """Raise an exception containing secrets to exercise CLI sanitization."""

        def get(self, url: str, *, timeout: float) -> keycloak_token.OidcHttpResponse:
            """Fail discovery with a message that must not reach the user."""
            raise RuntimeError("request leaked user-password client-secret")

    exit_code = keycloak_token.main(
        [
            "--issuer-url",
            "https://identity.example/realms/agents",
            "--client-id",
            "inspector",
            "--username",
            "alice",
            "--password",
            "user-password",
            "--client-secret",
            "client-secret",
        ],
        transport=FailingTransport(),
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "user-password" not in captured.out + captured.err
    assert "client-secret" not in captured.out + captured.err
    assert "RuntimeError" in captured.err
