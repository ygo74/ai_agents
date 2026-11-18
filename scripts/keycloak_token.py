"""Obtain a Keycloak access token and display its locally decoded claims."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True, slots=True)
class TokenRequest:
    """Hold validated OIDC inputs without exposing credentials in representations."""

    issuer_url: str
    client_id: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    client_secret: str | None = field(default=None, repr=False)
    scope: str | None = None
    timeout: float = 10.0


@dataclass(frozen=True, slots=True)
class OidcHttpResponse:
    """Contain an HTTP status and decoded JSON payload returned by the transport."""

    status_code: int
    payload: object


class OidcTransport(Protocol):
    """Define the small HTTP boundary required by discovery and token exchange."""

    def get(self, url: str, *, timeout: float) -> OidcHttpResponse:
        """Fetch one OIDC discovery document."""
        ...

    def post_form(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        auth: tuple[str, str] | None,
        timeout: float,
    ) -> OidcHttpResponse:
        """Submit one form-encoded password grant."""
        ...


class HttpxOidcTransport(OidcTransport):
    """Perform OIDC requests with certificate verification and bounded timeouts."""

    def get(self, url: str, *, timeout: float) -> OidcHttpResponse:
        """Fetch discovery metadata over verified HTTPS."""
        return self._request("GET", url, timeout=timeout)

    def post_form(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        auth: tuple[str, str] | None,
        timeout: float,
    ) -> OidcHttpResponse:
        """Submit credentials in a form body and optional Basic client auth."""
        return self._request("POST", url, data=data, auth=auth, timeout=timeout)

    def _request(
        self,
        method: str,
        url: str,
        *,
        timeout: float,
        data: Mapping[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> OidcHttpResponse:
        """Make one request and discard non-JSON response content."""
        # A separate short-lived client keeps transport state out of the token
        # flow and ensures redirects cannot forward credentials elsewhere.
        with httpx.Client(verify=True, timeout=timeout, follow_redirects=False) as client:
            response = client.request(method, url, data=data, auth=auth)

        try:
            payload: object = response.json()
        except ValueError:
            # Error pages and malformed bodies are never retained or printed.
            payload = None
        return OidcHttpResponse(status_code=response.status_code, payload=payload)


class KeycloakTokenError(Exception):
    """Describe a safe, user-facing failure without retaining credentials or responses."""

    def __init__(self, message: str, error_type: str | None = None) -> None:
        """Store only a reviewed message and optional exception class name."""
        self.message = message
        self.error_type = error_type
        suffix = f" ({error_type})" if error_type else ""
        super().__init__(f"{message}{suffix}")


def _is_valid_issuer_url(value: str) -> bool:
    """Check that an issuer is a clean HTTPS URL without embedded credentials."""
    try:
        issuer = urlsplit(value)
        return (
            bool(value)
            and value == value.strip()
            and issuer.scheme == "https"
            and issuer.hostname is not None
            and issuer.username is None
            and issuer.password is None
            and not issuer.query
            and not issuer.fragment
        )
    except ValueError:
        return False


def _validate_request(request: TokenRequest) -> None:
    """Reject unsafe issuer URLs and incomplete or invalid command settings."""
    # Check scalar inputs before building an endpoint or invoking the injected
    # transport, so invalid values cannot result in a credential-bearing call.
    if not _is_valid_issuer_url(request.issuer_url):
        raise KeycloakTokenError("Provide a valid HTTPS issuer URL without credentials, query, or fragment")
    if not request.client_id.strip():
        raise KeycloakTokenError("Client ID cannot be empty")
    if not request.username.strip() or not request.password:
        raise KeycloakTokenError("Username and password must not be empty")
    if request.client_secret == "":
        raise KeycloakTokenError("Client secret cannot be empty when supplied")
    if request.scope is not None and not request.scope.strip():
        raise KeycloakTokenError("Scope cannot be empty when supplied")
    if not math.isfinite(request.timeout) or request.timeout <= 0:
        raise KeycloakTokenError("Timeout must be a positive number")


def _discovery_document(request: TokenRequest, transport: OidcTransport) -> Mapping[str, Any]:
    """Load and validate the discovery metadata for the configured issuer."""
    issuer_url = request.issuer_url.rstrip("/")
    discovery_url = f"{issuer_url}/.well-known/openid-configuration"
    try:
        response = transport.get(discovery_url, timeout=request.timeout)
    except Exception as error:  # noqa: BLE001 - sanitize any injected/HTTP transport failure.
        raise KeycloakTokenError("OIDC discovery request failed", type(error).__name__) from None

    if response.status_code != 200:
        raise KeycloakTokenError(f"OIDC discovery request failed (HTTP {response.status_code})")
    if not isinstance(response.payload, Mapping):
        raise KeycloakTokenError("OIDC discovery response was not a JSON object")

    # OIDC requires the metadata issuer to identify the configured issuer. The
    # token endpoint must also be HTTPS before any user credentials are sent.
    metadata_issuer = response.payload.get("issuer")
    token_endpoint = response.payload.get("token_endpoint")
    if metadata_issuer != issuer_url:
        raise KeycloakTokenError("Discovered issuer does not match the configured issuer")
    if not isinstance(token_endpoint, str):
        raise KeycloakTokenError("OIDC discovery response has no token endpoint")
    try:
        endpoint = urlsplit(token_endpoint)
        valid_endpoint = (
            endpoint.scheme == "https"
            and endpoint.hostname is not None
            and endpoint.username is None
            and endpoint.password is None
            and not endpoint.query
            and not endpoint.fragment
        )
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint:
        raise KeycloakTokenError("Discovered token endpoint must be a safe HTTPS URL")
    return response.payload


def obtain_access_token(request: TokenRequest, transport: OidcTransport) -> str:
    """Use discovery and Direct Access Grants to obtain an access token."""
    _validate_request(request)
    metadata = _discovery_document(request, transport)
    token_endpoint = metadata["token_endpoint"]

    # Public clients identify themselves in the form; confidential clients
    # authenticate with HTTP Basic so the secret is not duplicated in the body.
    form_data = {
        "grant_type": "password",
        "username": request.username,
        "password": request.password,
    }
    auth: tuple[str, str] | None = None
    if request.client_secret is None:
        form_data["client_id"] = request.client_id
    else:
        auth = (request.client_id, request.client_secret)
    if request.scope is not None:
        form_data["scope"] = request.scope

    try:
        response = transport.post_form(token_endpoint, data=form_data, auth=auth, timeout=request.timeout)
    except Exception as error:  # noqa: BLE001 - sanitize any injected/HTTP transport failure.
        raise KeycloakTokenError("Token request failed", type(error).__name__) from None

    if response.status_code != 200:
        raise KeycloakTokenError(
            f"Keycloak rejected the token request (HTTP {response.status_code}). "
            "Check that Direct Access Grants are enabled and the account can use this flow."
        )
    if not isinstance(response.payload, Mapping):
        raise KeycloakTokenError("Token response was not a JSON object")
    access_token = response.payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise KeycloakTokenError("Token response did not contain an access token")
    return access_token


def decode_jwt_claims(access_token: str) -> dict[str, Any] | None:
    """Decode a JWT payload locally without validating its signature."""
    parts = access_token.split(".")
    if len(parts) != 3:
        return None

    try:
        # JWT segments use URL-safe Base64 without required padding. Validate
        # the alphabet and accept only a JSON object as a claim set.
        payload_segment = parts[1]
        padded_segment = payload_segment + "=" * (-len(payload_segment) % 4)
        decoded_payload = base64.b64decode(padded_segment, altchars=b"-_", validate=True)
        claims = json.loads(decoded_payload)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(claims, dict):
        return None
    return claims


def _argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for Keycloak Direct Access Grants."""
    parser = argparse.ArgumentParser(
        description="Obtain a Keycloak access token and display its locally decoded JWT claims."
    )
    parser.add_argument("--issuer-url", required=True, help="Keycloak realm issuer URL (HTTPS).")
    parser.add_argument("--client-id", required=True, help="OIDC client ID.")
    parser.add_argument("--username", required=True, help="Keycloak username.")
    parser.add_argument("--password", required=True, help="Keycloak user password.")
    parser.add_argument("--client-secret", help="Optional confidential-client secret.")
    parser.add_argument("--scope", help="Optional space-separated OIDC scopes.")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds (default: 10).")
    return parser


def main(arguments: Sequence[str] | None = None, *, transport: OidcTransport | None = None) -> int:
    """Run the token utility and return zero on success or one on failure."""
    parser = _argument_parser()
    parsed = parser.parse_args(arguments)
    request = TokenRequest(
        issuer_url=parsed.issuer_url,
        client_id=parsed.client_id,
        username=parsed.username,
        password=parsed.password,
        client_secret=parsed.client_secret,
        scope=parsed.scope,
        timeout=parsed.timeout,
    )

    try:
        selected_transport = transport if transport is not None else HttpxOidcTransport()
        access_token = obtain_access_token(request, selected_transport)
    except KeycloakTokenError as error:
        # Only the reviewed safe error is printed; transport exception details
        # and OAuth response bodies may contain credentials and are discarded.
        print(f"Authentication failed: {error}", file=sys.stderr)
        return 1

    print(f"Bearer {access_token}")
    claims = decode_jwt_claims(access_token)
    if claims is None:
        print("Claims could not be decoded (the token may be opaque, encrypted, or malformed).")
        return 0

    print("Decoded JWT claims (unverified):")
    print(json.dumps(claims, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
