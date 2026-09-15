"""How a wiki MCP server decides who may call it.

The mail server's module with a different prefix, and nothing else. Both delegate to
``ygo74-agent-runtime-mcp``, which is what stops two servers in one repository from
growing two different answers to "who may call me".

See :mod:`mail_mcp.protocol.authentication` for what each mode means. One difference
in emphasis: a wiki restricts pages per person, so ``jwt`` is the mode that lets the
agent act *on behalf of* the person asking rather than as one service account.
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

PREFIX = "WIKI_MCP_"

# Who the shared secret authenticates: a deployment, not a person.
DEPLOYED_AGENT = "wiki-agent"

MODE_VARIABLE = f"{PREFIX}{MODE_SUFFIX}"
TOKEN_VARIABLE = f"{PREFIX}{TOKEN_SUFFIX}"
ISSUER_VARIABLE = f"{PREFIX}{ISSUER_SUFFIX}"
AUDIENCE_VARIABLE = f"{PREFIX}{AUDIENCE_SUFFIX}"
RESOURCE_VARIABLE = f"{PREFIX}{RESOURCE_SUFFIX}"


class WikiMcpAuthentication:
    """Reads the wiki server's authentication from the environment."""

    @staticmethod
    def from_environment(environment: dict[str, str] | None = None) -> McpServerAuthentication:
        """Return the configured authentication, or refuse to serve."""
        return McpServerAuthentication.from_env(
            PREFIX,
            caller_id=DEPLOYED_AGENT,
            environment=environment,
        )
