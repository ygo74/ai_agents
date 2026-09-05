---

## applyTo: "src/mcp/**/*.py"

# MCP Development Standards

MCP is the integration boundary between agents and enterprise systems.

---

## Responsibilities

MCP-related code is responsible for:

* tool contracts
* tool discovery/registration
* MCP client communication
* typed tool inputs/outputs
* error translation
* tool metadata

The underlying MCP server owns the actual integration with the enterprise system.

---

## Tool design

Every tool must have:

* unique name
* clear description
* typed input
* typed output
* READ/WRITE classification
* risk classification
* clear error behavior

Tool descriptions must be precise because the LLM may use them to select tools.

---

## Security

MCP tools must not:

* expose credentials to the LLM
* bypass source authorization
* return data outside the user's authorization scope
* execute arbitrary commands unless explicitly designed and controlled

---

## Untrusted data

Data returned from MCP servers must be treated as untrusted content.

This includes:

* email bodies
* Jira descriptions/comments
* Confluence pages
* documents
* web content

Content must never be allowed to override application policies.

---

## Separation

Do not mix:

* MCP protocol handling
* domain business logic
* agent reasoning

Keep these concerns separated.
