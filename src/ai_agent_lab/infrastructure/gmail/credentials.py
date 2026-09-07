"""Google credentials for the Gmail API.

The authorisation-code flow is implemented here rather than taken from a Google
library, for two reasons: it keeps the dependency list short, and it lets us
request ``access_type=offline`` so Google actually issues a refresh token. The
MCP flow does not, which is why that grant expires after an hour.

Nothing here escapes the infrastructure layer. The access token is held in
memory, the refresh token is written to a file with owner-only permissions, and
neither ever reaches a prompt, a log or the domain.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_agent_lab.domain.errors import DomainError
from ai_agent_lab.infrastructure.config.settings import ENV_FILE
from ai_agent_lab.infrastructure.oauth.loopback import LoopbackConsent

AUTHORISATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a credential

READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
DEFAULT_SCOPES = f"{READ_SCOPE} {COMPOSE_SCOPE} {MODIFY_SCOPE}"

_EXPIRY_MARGIN_SECONDS = 60


class GoogleAuthorisationError(DomainError):
    """Raised when Google refuses to issue or refresh a token."""


class GmailCredentialSettings(BaseSettings):
    """Identity of the OAuth client used against the Gmail API."""

    model_config = SettingsConfigDict(
        env_prefix="GMAIL_OAUTH_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    # The same port as the MCP flow on purpose: the two never run at once, and
    # reusing it means the redirect URI already registered with Google works.
    callback_port: int = 8765
    scopes: str = DEFAULT_SCOPES
    token_file: Path = Path(".secrets/gmail-token.json")

    def require_client(self) -> None:
        """Fail with an actionable message when no client was configured."""
        if self.client_id and self.client_secret.get_secret_value():
            return
        raise GoogleAuthorisationError(
            "the Gmail API needs an OAuth client. Set GMAIL_OAUTH_CLIENT_ID and "
            f"GMAIL_OAUTH_CLIENT_SECRET in .env, and register {LoopbackConsent(self.callback_port).redirect_uri} "
            "as an authorised redirect URI."
        )


class GmailCredentials:
    """Supplies a valid access token, refreshing or asking for consent."""

    def __init__(self, settings: GmailCredentialSettings | None = None) -> None:
        self._settings = settings or GmailCredentialSettings()
        self._consent = LoopbackConsent(self._settings.callback_port)
        self._access_token = ""
        self._expires_at = 0.0

    async def access_token(self) -> str:
        """Return a token that is valid now."""
        if self._access_token and time.time() < self._expires_at - _EXPIRY_MARGIN_SECONDS:
            return self._access_token
        stored = self._stored()
        if stored.get("refresh_token"):
            return await self._refresh(str(stored["refresh_token"]))
        return await self.authorise()

    async def authorise(self) -> str:
        """Ask the person to approve access, then keep the grant."""
        self._settings.require_client()
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        await self._consent.open_consent(self._authorisation_url(verifier, state))
        code, returned_state = await self._consent.await_code()
        if returned_state != state:
            raise GoogleAuthorisationError("the authorisation response did not match the request")
        return await self._exchange(code, verifier)

    def granted_scopes(self) -> str:
        """Return the scopes the stored grant carries."""
        return str(self._stored().get("scope", ""))

    def _authorisation_url(self, verifier: str, state: str) -> str:
        """Build the consent URL.

        ``access_type=offline`` with ``prompt=consent`` is what makes Google
        return a refresh token; without both, the grant dies within the hour.
        """
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        parameters = {
            "response_type": "code",
            "client_id": self._settings.client_id,
            "redirect_uri": self._consent.redirect_uri,
            "scope": self._settings.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTHORISATION_ENDPOINT}?{urlencode(parameters)}"

    async def _exchange(self, code: str, verifier: str) -> str:
        """Trade the authorisation code for tokens."""
        issued = await self._post(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._consent.redirect_uri,
                "code_verifier": verifier,
            }
        )
        self._store(issued)
        return self._accept(issued)

    async def _refresh(self, refresh_token: str) -> str:
        """Renew the access token without asking again."""
        try:
            issued = await self._post({"grant_type": "refresh_token", "refresh_token": refresh_token})
        except GoogleAuthorisationError:
            # A revoked or expired grant is recoverable: ask for consent again
            # rather than leaving the agent permanently unusable.
            return await self.authorise()
        self._store({"refresh_token": refresh_token, **issued})
        return self._accept(issued)

    async def _post(self, payload: dict[str, str]) -> dict[str, Any]:
        """Call the token endpoint with the configured client."""
        self._settings.require_client()
        body = {
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret.get_secret_value(),
            **payload,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(TOKEN_ENDPOINT, data=body)
        if response.status_code != httpx.codes.OK:
            raise GoogleAuthorisationError(f"Google refused the token request ({response.status_code})")
        issued: dict[str, Any] = response.json()
        return issued

    def _accept(self, issued: dict[str, Any]) -> str:
        """Remember an issued token and return it."""
        token = str(issued.get("access_token", ""))
        if not token:
            raise GoogleAuthorisationError("Google returned no access token")
        self._access_token = token
        self._expires_at = time.time() + float(issued.get("expires_in", 0))
        return token

    def _stored(self) -> dict[str, Any]:
        """Return the grant kept from a previous run, if any."""
        path = self._settings.token_file
        if not path.is_file():
            return {}
        try:
            stored: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A damaged file costs a new consent, never a crash.
            return {}
        return stored

    def _store(self, issued: dict[str, Any]) -> None:
        """Keep the grant for the next run, readable by its owner only."""
        path = self._settings.token_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(issued), encoding="utf-8")
        path.chmod(0o600)
