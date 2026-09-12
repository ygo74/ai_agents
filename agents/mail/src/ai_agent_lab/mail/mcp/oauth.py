"""OAuth 2.0 authentication against a remote mail MCP server.

This is the one place in the repository that holds an OAuth client credential.
It stays here: no token, no client secret and no authorisation code ever reaches
a prompt, a log, a ``UserContext`` or the domain layer. Secrets are held as
``SecretStr`` so that logging a settings object cannot leak them.

Google does not support dynamic client registration for its MCP endpoint, so the
client is registered once in the Google Cloud console and its identity is
supplied here rather than negotiated.
"""

from __future__ import annotations

import json
import logging
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import anyio
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_agent_lab.core.config.environment import ENV_FILE
from ai_agent_lab.mail.mail_errors import MailToolUnavailableError

GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose"

_CALLBACK_PATH = "/oauth/callback"
_LOOPBACK = "127.0.0.1"
# Google issues a confidential client for a web application and refuses a token
# exchange that carries no secret, so the default public-client method does not
# apply here. This is the name of an OAuth method, not a credential.
_CLIENT_SECRET_POST: Literal["client_secret_post"] = "client_secret_post"  # noqa: S105
_DONE = (
    "<html><body><h3>Authorisation received.</h3>"
    "<p>You can close this tab and return to the terminal.</p></body></html>"
)
_logger = logging.getLogger(__name__)


class MailOAuthSettings(BaseSettings):
    """Identity of the OAuth client used to reach a remote mail MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="MAIL_MCP_OAUTH_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    callback_port: int = 8765
    scopes: str = GMAIL_SCOPES
    token_file: Path = Path(".secrets/mail-mcp-token.json")

    @property
    def redirect_uri(self) -> str:
        """Where the authorisation server sends the user back."""
        return f"http://localhost:{self.callback_port}{_CALLBACK_PATH}"

    def require_client(self) -> None:
        """Fail with an actionable message when no client was configured."""
        _logger.info("Validating Mail MCP OAuth client configuration")
        _logger.debug(
            "MailOAuthSettings.require_client arguments: client_id_configured=%s, "
            "client_secret_configured=%s, callback_port=%d, scope_count=%d",
            bool(self.client_id),
            bool(self.client_secret.get_secret_value()),
            self.callback_port,
            len(self.scopes.split()),
        )
        if self.client_id and self.client_secret.get_secret_value():
            return
        raise MailToolUnavailableError(
            "this server needs an OAuth client. Set MAIL_MCP_OAUTH_CLIENT_ID and "
            "MAIL_MCP_OAUTH_CLIENT_SECRET in .env, and register "
            f"{self.redirect_uri} as an authorised redirect URI."
        )


class FileTokenStorage(TokenStorage):
    """Keeps the issued tokens on disk, between runs.

    The client identity is not stored: it is configuration, supplied on every
    start, which also means a rotated secret takes effect immediately.
    """

    def __init__(self, settings: MailOAuthSettings) -> None:
        _logger.info("Initializing Mail MCP OAuth token storage")
        _logger.debug(
            "FileTokenStorage.__init__ arguments: token_file_name=%s",
            settings.token_file.name,
        )
        self._settings = settings

    async def get_tokens(self) -> OAuthToken | None:
        """Return the tokens of a previous authorisation, if any."""
        path = self._settings.token_file
        _logger.info("Reading stored Mail MCP OAuth tokens")
        _logger.debug(
            "FileTokenStorage.get_tokens arguments: token_file_name=%s, exists=%s",
            path.name,
            path.is_file(),
        )
        if not path.is_file():
            return None
        try:
            return OAuthToken.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A damaged token file must cost a new consent, never a crash.
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Persist the issued tokens for the next run."""
        path = self._settings.token_file
        _logger.info("Persisting Mail MCP OAuth tokens")
        _logger.debug(
            "FileTokenStorage.set_tokens arguments: token_type=%s, token_file_name=%s",
            tokens.token_type,
            path.name,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tokens.model_dump_json(), encoding="utf-8")
        path.chmod(0o600)

    async def get_client_info(self) -> OAuthClientInformationFull:
        """Return the pre-registered client, so no dynamic registration happens."""
        _logger.info("Building Mail MCP OAuth client information")
        _logger.debug(
            "FileTokenStorage.get_client_info arguments: callback_port=%d, scope_count=%d",
            self._settings.callback_port,
            len(self._settings.scopes.split()),
        )
        self._settings.require_client()
        return OAuthClientInformationFull(
            client_id=self._settings.client_id,
            client_secret=self._settings.client_secret.get_secret_value(),
            redirect_uris=[self._settings.redirect_uri],  # type: ignore[list-item]
            scope=self._settings.scopes,
            client_name="AI Agent Lab Mail Agent",
            token_endpoint_auth_method=_CLIENT_SECRET_POST,
        )

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Ignore a registration result: the client is configured, not negotiated."""
        _logger.info("Ignoring dynamic Mail MCP OAuth client registration")
        _logger.debug(
            "FileTokenStorage.set_client_info arguments: client_info_type=%s",
            type(client_info).__name__,
        )
        del client_info


class LoopbackAuthorisationListener:
    """Receives the authorisation redirect on the loopback interface."""

    def __init__(self, port: int) -> None:
        _logger.info("Initializing Mail MCP OAuth loopback listener")
        _logger.debug("LoopbackAuthorisationListener.__init__ arguments: port=%d", port)
        self._port = port

    async def open_consent(self, authorization_url: str) -> None:
        """Send the person to the authorisation page."""
        _logger.info("Opening Mail MCP OAuth consent page")
        _logger.debug(
            "LoopbackAuthorisationListener.open_consent arguments: authorization_url_length=%d",
            len(authorization_url),
        )
        print(f"\nAuthorise the Mail Agent in your browser:\n  {authorization_url}\n")
        webbrowser.open(authorization_url)

    async def await_code(self) -> tuple[str, str | None]:
        """Wait for the redirect and return the code and state it carried."""
        _logger.info("Waiting for Mail MCP OAuth callback")
        _logger.debug(
            "LoopbackAuthorisationListener.await_code arguments: port=%d",
            self._port,
        )
        return await anyio.to_thread.run_sync(self._serve_once)

    def _serve_once(self) -> tuple[str, str | None]:
        """Serve exactly one redirect, then stop listening."""
        _logger.info("Serving one Mail MCP OAuth callback")
        _logger.debug(
            "LoopbackAuthorisationListener._serve_once arguments: port=%d",
            self._port,
        )
        captured: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                captured.update({key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_DONE.encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                """Keep the authorisation code out of the console."""
                del format, args

        with HTTPServer((_LOOPBACK, self._port), Handler) as server:
            server.handle_request()

        if "code" not in captured:
            raise MailToolUnavailableError(f"authorisation failed: {captured.get('error', 'no code was returned')}")
        return captured["code"], captured.get("state")


class PinnedScopeOAuthProvider(OAuthClientProvider):
    """Requests only the scopes the agent actually needs.

    The SDK replaces the configured scope with whatever the resource server
    advertises, and re-widens it when a call comes back with
    ``insufficient_scope``. For the official Gmail server that advertised set
    includes ``https://mail.google.com/`` - full mailbox control, permanent
    deletion included - which is far beyond reading messages, applying labels
    and preparing drafts.

    Re-pinning before every authorisation attempt neutralises both the initial
    widening and the later step-up. If the server genuinely refuses to work
    within these scopes, the call fails and says so, which is a better outcome
    than silently holding a key to the whole mailbox.
    """

    def __init__(self, *args: Any, pinned_scope: str, **kwargs: Any) -> None:
        _logger.info("Initializing pinned-scope Mail MCP OAuth provider")
        _logger.debug(
            "PinnedScopeOAuthProvider.__init__ arguments: positional_count=%d, keyword_names=%s, scope_count=%d",
            len(args),
            tuple(sorted(kwargs)),
            len(pinned_scope.split()),
        )
        super().__init__(*args, **kwargs)
        self._pinned_scope = pinned_scope

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        """Ask for the pinned scopes, whatever the server advertised."""
        _logger.info("Performing Mail MCP OAuth authorization-code grant")
        _logger.debug(
            "PinnedScopeOAuthProvider._perform_authorization_code_grant arguments: scope_count=%d",
            len(self._pinned_scope.split()),
        )
        self.context.client_metadata.scope = self._pinned_scope
        return await super()._perform_authorization_code_grant()


class MailOAuthProvider:
    """Builds the authentication attached to a remote MCP transport."""

    def __init__(self, settings: MailOAuthSettings | None = None) -> None:
        _logger.info("Initializing Mail MCP OAuth provider factory")
        _logger.debug(
            "MailOAuthProvider.__init__ arguments: injected_settings=%s",
            settings is not None,
        )
        self._settings = settings or MailOAuthSettings()

    def build(self, server_url: str) -> OAuthClientProvider:
        """Return the OAuth client the HTTP transport authenticates with."""
        _logger.info("Building Mail MCP OAuth provider")
        _logger.debug(
            "MailOAuthProvider.build arguments: server_url_configured=%s, callback_port=%d, scope_count=%d",
            bool(server_url),
            self._settings.callback_port,
            len(self._settings.scopes.split()),
        )
        self._settings.require_client()
        listener = LoopbackAuthorisationListener(self._settings.callback_port)
        return PinnedScopeOAuthProvider(
            server_url=server_url,
            client_metadata=OAuthClientMetadata(
                client_name="AI Agent Lab Mail Agent",
                redirect_uris=[self._settings.redirect_uri],  # type: ignore[list-item]
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope=self._settings.scopes,
                token_endpoint_auth_method=_CLIENT_SECRET_POST,
            ),
            storage=FileTokenStorage(self._settings),
            redirect_handler=listener.open_consent,
            callback_handler=listener.await_code,
            pinned_scope=self._settings.scopes,
        )


def describe_tools(payload: object) -> str:
    """Render a tool listing as readable JSON, for the discovery step."""
    return json.dumps(payload, indent=2, sort_keys=True, default=str)
