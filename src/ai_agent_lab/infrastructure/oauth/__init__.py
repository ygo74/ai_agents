"""Shared OAuth building blocks.

Both the MCP client and the Gmail API client need a person to approve a grant in
a browser and a way to catch the redirect. That mechanism has nothing to do with
either protocol, so it lives here rather than being written twice.
"""

from __future__ import annotations
