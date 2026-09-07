"""Gmail MCP server package.

Everything Gmail-specific lives here: the query syntax, the payload shapes the
server returns, and the client that reconciles them with the mail contract. No
other layer knows that Gmail exists.
"""

from __future__ import annotations
