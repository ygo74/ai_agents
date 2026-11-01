"""Select a single backend for agents whose typed tools share one connection."""

from ygo74.agent_runtime.domains.configuration.manifests import ConfigurationError
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest


class SingleMcpBackendSelector:
    """Resolve skill overrides and agent defaults without silently misrouting tools."""

    @staticmethod
    def server_for(manifest: AgentManifest) -> str:
        """Return the one effective server, rejecting missing or conflicting bindings."""
        servers = {skill.mcp_server or manifest.mcp_server for skill in manifest.skills if skill.mcp_tools}
        if not servers:
            servers = {manifest.mcp_server}
        if None in servers:
            raise ConfigurationError(
                "MCP skills must declare mcp_server in skill.yaml or inherit it from the agent manifest"
            )
        if len(servers) != 1:
            raise ConfigurationError("Skills must share one MCP server; multiple backends are not supported")
        server = next(iter(servers))
        if server is None:
            raise ConfigurationError("Agent manifest must declare mcp_server")
        return server
