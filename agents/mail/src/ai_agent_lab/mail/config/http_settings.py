"""Settings of the Mail Agent HTTP service.

Only routing and posture live here. No credential is read, held or logged: the
API key of the demonstration mode is compared, never stored anywhere it could be
printed, and OIDC tokens are validated against a public key set.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_agent_lab.core.config.environment import ENV_FILE


class MailAgentHttpSettings(BaseSettings):
    """How the Mail Agent is served over HTTP."""

    model_config = SettingsConfigDict(
        env_prefix="MAIL_AGENT_HTTP_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Demonstration mode: one key, one caller. Ignored once an issuer is set.
    api_key: str = ""

    oidc_issuer: str = ""
    oidc_audience: str = "mail-agent"
    jwks_url_override: str = Field(default="", validation_alias="MAIL_AGENT_HTTP_JWKS_URL")
    roles_claim_path: str = "realm_access.roles"

    max_conversations: int = 200
    idle_minutes: int = 30

    @property
    def requires_authentication(self) -> bool:
        """Whether a caller must present something.

        An unauthenticated service would have no subject to partition state by,
        so refusing to run open is the only safe default. Serving without either
        an issuer or a key is therefore a configuration error rather than an
        anonymous mode.
        """
        return True

    def jwks_url(self) -> str:
        """Where the signing keys of the issuer are published."""
        if self.jwks_url_override:
            return self.jwks_url_override
        return f"{self.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"

    def idle_lifetime(self) -> timedelta:
        """How long an untouched conversation is kept."""
        return timedelta(minutes=self.idle_minutes)
