"""How a mail MCP server decides who may call it.

Everything here is a name. The schemes come from ``ygo74-agent-runtime-security``
and the environment mapping from ``ygo74-agent-runtime-mcp``; what this module adds
is the prefix this repository's variables use and who the shared secret stands for.

That is deliberately all it adds. The wiki server has the same module with a
different prefix, and if either grew logic of its own the two would start answering
"who may call me" differently - which is how a weaker answer appears without anybody
deciding it should.

Three modes:

``none``
    Anonymous. Legitimate for a server over public, read-only data. It has to be
    written down: absence of configuration is a refusal, not anonymity.
``api_key``
    A shared secret, presented as ``Authorization: Bearer <secret>``. It says "you
    are the agent I was deployed with" and nothing about whose mailbox is read -
    that was settled by the Google credential the server itself holds.
``jwt``
    A token from an OIDC issuer. The server then behaves as an OAuth 2.1 resource
    server, so a generic MCP client can discover the issuer from the URL alone.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.mcpserver.settings import (
    AUDIENCE_SUFFIX,
    ISSUER_SUFFIX,
    MODE_SUFFIX,
    RESOURCE_SUFFIX,
    TOKEN_SUFFIX,
    McpServerAuthentication,
)

PREFIX = "MAIL_MCP_"

# Who the shared secret authenticates. One caller, named once: the secret proves a
# deployment, not a person, and inventing a richer identity here would suggest the
# server knows something about the caller that it does not.
DEPLOYED_AGENT = "mail-agent"

MODE_VARIABLE = f"{PREFIX}{MODE_SUFFIX}"
TOKEN_VARIABLE = f"{PREFIX}{TOKEN_SUFFIX}"
ISSUER_VARIABLE = f"{PREFIX}{ISSUER_SUFFIX}"
AUDIENCE_VARIABLE = f"{PREFIX}{AUDIENCE_SUFFIX}"
RESOURCE_VARIABLE = f"{PREFIX}{RESOURCE_SUFFIX}"


class MailMcpAuthentication:
    """Reads the mail server's authentication from the environment."""

    @staticmethod
    def from_environment(environment: dict[str, str] | None = None) -> McpServerAuthentication:
        """Return the configured authentication, or refuse to serve."""
        return McpServerAuthentication.from_env(
            PREFIX,
            caller_id=DEPLOYED_AGENT,
            environment=environment,
        )
