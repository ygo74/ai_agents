"""Enumerations of the mail domain."""

from __future__ import annotations

from enum import StrEnum


class MailCategory(StrEnum):
    """Business classification of a mail message.

    The catalogue is intentionally open for extension through configuration:
    :class:`MailCategoryCatalog` decides which categories are offered, this
    enumeration only fixes the vocabulary understood by the domain.
    """

    IMPORTANT = "IMPORTANT"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    FYI = "FYI"
    NEWSLETTER = "NEWSLETTER"
    PERSONAL = "PERSONAL"
    FINANCIAL = "FINANCIAL"
    PROJECT = "PROJECT"
    OTHER = "OTHER"


class ActionOrigin(StrEnum):
    """Whether an extracted action was stated or deduced.

    Inferred actions must never be presented to the user as facts.
    """

    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"


class ConfidenceLevel(StrEnum):
    """Qualitative confidence attached to an inferred result."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MailImportance(StrEnum):
    """Importance flag as reported by the mail system."""

    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class MailSortOrder(StrEnum):
    """Ordering applied to search results."""

    NEWEST_FIRST = "NEWEST_FIRST"
    OLDEST_FIRST = "OLDEST_FIRST"
