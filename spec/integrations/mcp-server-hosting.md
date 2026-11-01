# Mail and Wiki MCP servers

## Purpose and boundary

MCP servers expose typed domain tools to an agent without placing vendor API
clients inside the agent's skills. The agent-side tool port and dialect translate
between domain models and the server's protocol. A server implements a wire
contract; it does not import `ai_agent_lab` or know how an agent reasons.

## Server distributions

| Distribution | Role | Data source |
|---|---|---|
| `mail-mcp-protocol` | Mail tool names, payloads, errors, authentication metadata, and FastMCP surface | Contract only |
| `mail-mcp-reference` | Deterministic Mail server for tests and local scenarios | Sample mailbox dataset |
| `mail-mcp-gmail` | Separately deployed Mail server | Gmail API |
| `wiki-mcp-protocol` | Wiki tool names, payloads, errors, authentication metadata, and FastMCP surface | Contract only |
| `wiki-mcp-reference` | Deterministic Wiki server for tests and local scenarios | Sample Wiki dataset |

The repository does not contain a production Confluence MCP server. A real Wiki
deployment may use a compatible external server such as `mcp-atlassian`; the
agent-side Atlassian dialect maps that server's names and results to the Wiki
port. The agent does not depend on one server's wire names.

## Tool contract behavior

The Mail protocol covers message search/read, thread retrieval, labels, draft
creation, delivery, and mailbox organisation. The Wiki protocol covers search,
page retrieval and hierarchy, spaces, comments, page history, and page writes.
Each request and response has a typed payload; malformed payloads are errors,
not partial success. The reference servers provide deterministic conformance
targets for the same port used by real servers.

The model is not the server's authorization boundary. Authentication identifies
the calling service or user according to deployment. The server or source system
must enforce access to the requested mailbox, page, or space. Agent-side
permissions and confirmation gates provide additional checks before risky
operations.

## Authentication and lifecycle

HTTP server hosting is separate from the agent. Deployments may use an API key,
JWT/OIDC, or explicit anonymous mode where supported and deliberately selected.
An HTTP server that requires caller identity refuses to start without an
authentication policy. Stdio connections are local process relationships and
do not use HTTP authentication.

Authentication of an agent process is not automatically the same as the
end-user identity. Wiki deployments can pass caller-specific authorization to a
server that supports delegated access; Mail deployments may use configured
service or user credentials. The operator chooses secret storage, network
reachability, and identity propagation. Secrets are not part of prompts, MCP
tool arguments, or agent manifests.

Reference servers use local datasets and need no external provider. The Gmail
server uses Gmail credentials and OAuth permissions appropriate to its
operations. The Atlassian server is externally maintained and has its own
transport, authentication, and tool availability. Its declared bindings must
match the actual server surface. Read-only mode removes writes at both the
server and agent boundaries.

## Acceptance and limits

- Protocol payloads remain independent of agent domain classes and framework
  SDKs.
- Reference servers and production dialects satisfy the same typed tool port.
- Invalid server payloads or unavailable tools produce visible typed errors.
- Authentication and source authorization are explicit at deployment; a tool
  declaration does not grant access to data.
- Read-only server mode and agent capability filtering agree.
- Every MCP server remains separately installable and deployable from its
  corresponding agent.

See [Mail MCP server selection](../../doc/users/mail-mcp-servers.md),
[Wiki MCP server selection](../../doc/users/wiki-mcp-servers.md), and the
[deployment specification](../architecture/repository-structure.md). Tool
ports, wire contracts, and host implementations live under [`agents/`](../../agents/)
and [`mcp-servers/`](../../mcp-servers/).
