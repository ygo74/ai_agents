"""Settings of the Wiki Agent HTTP service.

Only routing and posture live here. No credential is read, held or logged: the
API key of the demonstration mode is compared, never stored anywhere it could be
printed, and OIDC tokens are validated against a public key set.

The variable names mirror the Mail Agent's, under their own prefix, so the two
services are configured the same way and a deployment learns one scheme rather
than two.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_agent_lab.core.config.environment import ENV_FILE


class WikiAgentHttpSettings(BaseSettings):
    """How the Wiki Agent is served over HTTP."""

    model_config = SettingsConfigDict(
        env_prefix="WIKI_AGENT_HTTP_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Demonstration mode: one key, one caller. Ignored once an issuer is set.
    api_key: str = ""

    oidc_issuer: str = ""
    oidc_audience: str = "wiki-agent"
    jwks_url_override: str = Field(default="", validation_alias="WIKI_AGENT_HTTP_JWKS_URL")
    roles_claim_path: str = "realm_access.roles"

    max_conversations: int = 200
    idle_minutes: int = 30

    @property
    def requires_authentication(self) -> bool:
        """Whether a caller must present something.

        An unauthenticated service would have no subject to partition state by,
        so refusing to run open is the only safe default. On a wiki that matters
        as much as on a mailbox: pages and spaces are restricted per person, and
        an anonymous caller would be served somebody's view of the wiki without
        anybody having decided whose.
        """
        return True

    @property
    def uses_oidc(self) -> bool:
        """Whether tokens are validated against an identity provider."""
        return bool(self.oidc_issuer)

    def jwks_url(self) -> str:
        """Where the signing keys of the issuer are published."""
        if self.jwks_url_override:
            return self.jwks_url_override
        return f"{self.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"

    def idle_lifetime(self) -> timedelta:
        """How long an untouched conversation is kept."""
        return timedelta(minutes=self.idle_minutes)
