"""Category membership and fallback rules independent of prompt wording."""

from ai_agent_lab.mail.domain.enums import MailCategory


class MailCategories:
    """The ordered category set a classification may use."""

    def __init__(self, categories: tuple[MailCategory, ...], fallback: MailCategory) -> None:
        if fallback not in categories:
            raise ValueError(f"fallback category {fallback} must be part of the catalogue")
        self._categories = categories
        self._fallback = fallback

    @property
    def fallback(self) -> MailCategory:
        """The category used when a proposed value is not offered."""
        return self._fallback

    def categories(self) -> tuple[MailCategory, ...]:
        """Return the configured priority order."""
        return self._categories

    def contains(self, category: MailCategory) -> bool:
        """Whether classification can assign this value."""
        return category in self._categories

    def normalise(self, category: MailCategory) -> MailCategory:
        """Keep an offered category or use the configured fallback."""
        return category if self.contains(category) else self._fallback
