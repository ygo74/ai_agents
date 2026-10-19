"""Stable names of the mailbox operations understood by the domain."""

from enum import StrEnum


class MailToolName(StrEnum):
    """Identifiers independent of a server's remote tool names."""

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
