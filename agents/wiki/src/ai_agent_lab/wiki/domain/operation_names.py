"""Stable names of the wiki operations understood by the domain."""

from enum import StrEnum


class WikiToolName(StrEnum):
    """Identifiers independent of a server's remote tool names."""

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
