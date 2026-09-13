"""Configurable catalogue of mail categories.

Classification rules must not be hardcoded inside the agent. The catalogue
decides which categories exist and how each one is described to the reasoner,
so a deployment can restrict or re-word them without touching the skill.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from ai_agent_lab.mail.domain.enums import MailCategory

DEFAULT_CATEGORY_DESCRIPTIONS: Mapping[MailCategory, str] = {
    MailCategory.ACTION_REQUIRED: "The recipient is explicitly asked to do or decide something.",
    MailCategory.IMPORTANT: "Business critical or time critical, but no explicit request for the recipient.",
    MailCategory.PROJECT: "Ongoing project work: status, planning, technical discussion.",
    MailCategory.FINANCIAL: "Invoice, payment, quote, budget or accounting matter.",
    MailCategory.PERSONAL: "Private correspondence unrelated to work.",
    MailCategory.NEWSLETTER: "Bulk or subscription content, marketing, automated digest.",
    MailCategory.FYI: "Shared for information only, no action expected.",
    MailCategory.OTHER: "Nothing else applies.",
}
_logger = logging.getLogger(__name__)


class MailCategoryCatalog:
    """The set of categories a classification skill may assign.

    Args:
        descriptions: Categories offered to the reasoner, in priority order.
        fallback: Category used when the reasoner proposes an unknown value.
    """

    def __init__(
        self,
        descriptions: Mapping[MailCategory, str] | None = None,
        *,
        fallback: MailCategory = MailCategory.OTHER,
    ) -> None:
        _logger.info("Initializing Mail category catalog")
        _logger.debug(
            "MailCategoryCatalog.__init__ arguments: configured_descriptions=%s, category_count=%d, fallback=%s",
            descriptions is not None,
            len(descriptions or DEFAULT_CATEGORY_DESCRIPTIONS),
            fallback.value,
        )
        self._descriptions = dict(descriptions or DEFAULT_CATEGORY_DESCRIPTIONS)
        if fallback not in self._descriptions:
            raise ValueError(f"fallback category {fallback} must be part of the catalogue")
        self._fallback = fallback

    @property
    def fallback(self) -> MailCategory:
        """Category assigned when no offered category applies."""
        _logger.info("Reading Mail category fallback")
        _logger.debug("MailCategoryCatalog.fallback arguments: none")
        return self._fallback

    def categories(self) -> tuple[MailCategory, ...]:
        """Every category offered, in the configured order."""
        _logger.info("Listing Mail category catalog")
        _logger.debug(
            "MailCategoryCatalog.categories arguments: category_count=%d",
            len(self._descriptions),
        )
        return tuple(self._descriptions)

    def contains(self, category: MailCategory) -> bool:
        """Whether a category is part of the catalogue."""
        _logger.info("Checking Mail category membership")
        _logger.debug(
            "MailCategoryCatalog.contains arguments: category=%s",
            category.value,
        )
        return category in self._descriptions

    def normalise(self, category: MailCategory) -> MailCategory:
        """Return the category, or the fallback when it is not offered."""
        _logger.info("Normalizing Mail category")
        _logger.debug(
            "MailCategoryCatalog.normalise arguments: category=%s, fallback=%s",
            category.value,
            self._fallback.value,
        )
        return category if self.contains(category) else self._fallback

    def describe(self) -> str:
        """Render the catalogue for a reasoning prompt."""
        _logger.info("Rendering Mail category catalog loop")
        _logger.debug(
            "MailCategoryCatalog.describe arguments: category_count=%d",
            len(self._descriptions),
        )
        return "\n".join(f"- {category.value}: {description}" for category, description in self._descriptions.items())
