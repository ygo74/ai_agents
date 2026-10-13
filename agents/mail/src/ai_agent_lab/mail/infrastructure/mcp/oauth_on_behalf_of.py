"""Compatibility import for the runtime-owned RFC 8693 token source."""

from ygo74.agent_runtime.domains.auth.oauth_token_exchange import (
    Rfc8693OAuthOnBehalfOfTokenSource,
)

__all__ = ["Rfc8693OAuthOnBehalfOfTokenSource"]
