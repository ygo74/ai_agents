"""Names of the tools a wiki MCP server exposes.

The names are the protocol. What each one costs, who may call it and whether it
needs a confirmation are questions for the caller, not for the wire.
"""

from __future__ import annotations

from enum import StrEnum


class WikiToolName(StrEnum):
    """Stable identifiers of the wiki tools."""

    SEARCH_WIKI = "search_wiki"
    GET_PAGE = "get_page"
    GET_PAGE_CHILDREN = "get_page_children"
    LIST_SPACES = "list_spaces"
    GET_COMMENTS = "get_comments"
    GET_PAGE_HISTORY = "get_page_history"
    CREATE_PAGE = "create_page"
    UPDATE_PAGE = "update_page"
    ADD_COMMENT = "add_comment"
    DELETE_PAGE = "delete_page"
