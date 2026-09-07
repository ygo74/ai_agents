"""Names of the tools a mail MCP server exposes.

The names are the protocol. What each one costs, who may call it and whether it
needs a confirmation are questions for the caller, not for the wire.
"""

from __future__ import annotations

from enum import StrEnum


class MailToolName(StrEnum):
    """Stable identifiers of the mail tools."""

    SEARCH_MAIL = "search_mail"
    GET_MAIL = "get_mail"
    GET_THREAD = "get_thread"
    LIST_LABELS = "list_labels"
    CREATE_DRAFT = "create_draft"
    SEND_MAIL = "send_mail"
    MARK_READ = "mark_read"
    ARCHIVE_MAIL = "archive_mail"
    APPLY_LABEL = "apply_label"
    REMOVE_LABEL = "remove_label"
    CREATE_LABEL = "create_label"
    DELETE_LABEL = "delete_label"
