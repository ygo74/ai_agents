"""Human-facing acknowledgements for writes executed from confirmation tickets."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from urllib.parse import quote, urlsplit

from pydantic import BaseModel

from ai_agent_lab.wiki.adapters.capabilities.results import (
    WikiCommentPostedResult,
    WikiPageDeletedResult,
    WikiPageWrittenResult,
)

_MARKDOWN_ESCAPES = str.maketrans({character: f"\\{character}" for character in "\\`*_{}[]()#+.!|>~-"})


class WikiConfirmationResultRenderer:
    """Render typed write results for people, never for the model.

    Confirmed operations bypass the model. Its fenced tool renderer must stay
    separate; removing fences from that renderer would weaken read/tool safety.
    """

    def render(self, result: BaseModel | Sequence[BaseModel]) -> str:
        """Acknowledge the stored result without exposing internal tool JSON."""
        if isinstance(result, Sequence):
            return "\n\n".join(self.render(item) for item in result)
        if isinstance(result, WikiPageWrittenResult):
            return self._written_page(result)
        if isinstance(result, WikiPageDeletedResult):
            return self._details("Page deleted successfully.", [("Page", result.page_id)])
        if isinstance(result, WikiCommentPostedResult):
            return self._details(
                "Comment posted successfully.", [("Page", result.page_id), ("Comment", result.comment_id)]
            )
        raise TypeError(f"Unsupported Wiki confirmation result: {type(result).__name__}")

    def _written_page(self, result: WikiPageWrittenResult) -> str:
        fields = [("Title", result.title)] if result.title else []
        fields.extend([("Page", result.page_id), ("Space", result.space_key), ("Version", str(result.version))])
        acknowledgement = self._details("Page saved successfully.", fields)
        link = self._page_link(result.url)
        return f"{acknowledgement}\n\n{link}" if link else acknowledgement

    @staticmethod
    def _details(summary: str, fields: Sequence[tuple[str, str]]) -> str:
        rows = [f"- {label}: {escape(' '.join(value.split())).translate(_MARKDOWN_ESCAPES)}" for label, value in fields]
        return f"{summary}\n\n" + "\n".join(rows)

    @staticmethod
    def _page_link(url: str) -> str:
        if not url or any(character.isspace() for character in url):
            return ""
        try:
            parsed = urlsplit(url)
        except ValueError:
            # A malformed optional URL must not turn a completed write into an error.
            return ""
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        target = quote(url, safe=":/?#[]@!$&'*+,;=%~")
        return f"[Open page](<{target}>)"
