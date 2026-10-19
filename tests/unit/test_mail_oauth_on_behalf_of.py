"""The old Mail import path re-exports the runtime-owned RFC 8693 source."""

from ygo74.agent_runtime.domains.auth.oauth_token_exchange import (
    Rfc8693OAuthOnBehalfOfTokenSource as RuntimeOAuthOnBehalfOfTokenSource,
)

from ai_agent_lab.mail.infrastructure.mcp.oauth_on_behalf_of import (
    Rfc8693OAuthOnBehalfOfTokenSource,
)


def test_legacy_mail_import_points_to_the_runtime_implementation() -> None:
    """Existing imports resolve to the class implemented by the shared runtime."""
    assert Rfc8693OAuthOnBehalfOfTokenSource is RuntimeOAuthOnBehalfOfTokenSource
