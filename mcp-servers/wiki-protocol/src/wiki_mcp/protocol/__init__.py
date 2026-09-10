"""Wire protocol of a wiki MCP server.

This package carries the tool names, the payload shapes and the error codes, and
nothing else: no domain model, no security metadata, no untrusted-content
wrapper. A server that implements it needs no code on the caller's side.

It is an offer to server authors, never a requirement. The wiki MCP server this
repository actually targets - `sooperset/mcp-atlassian` - has never heard of it,
and is reached through a translating dialect on the agent side instead.
"""
