"""Gmail API package.

Our own mail MCP server is backed by this code. It is the only place that knows
the Gmail REST API exists, and the only place that holds a Google credential.

Why not the official Gmail MCP server? Because it is behind the Google Workspace
Developer Preview Program, which a personal account cannot join. The REST API it
sits on is generally available, so the integration lives here and is served
through our own MCP server - which keeps the agent exactly where it was, behind
the MCP boundary.
"""

from __future__ import annotations
