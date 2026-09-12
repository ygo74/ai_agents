"""Loading of wiki datasets stored as JSON.

Datasets are the reproducible input of the mock runtime mode and of the agent
scenarios. Everything the loader reads was written by a third party, so every
piece of free text is wrapped as untrusted content on the way in - titles,
bodies, excerpts, space names, comments, labels and version messages alike.

Wrapping happens *here*, at the edge, rather than wherever the text is later
used. A dataset that reached a skill as a plain string would have crossed the
boundary unnoticed, and nothing downstream could tell.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.wiki.domain.enums import WikiContentFormat, WikiPageStatus
from ai_agent_lab.wiki.domain.models import (
    WikiAuthor,
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageVersion,
    WikiSpace,
)
from ai_agent_lab.wiki.inmemory.wiki import PageEntry, SpaceEntry, Wiki
from ai_agent_lab.wiki.wiki_errors import WikiToolProtocolError

JsonObject = Mapping[str, Any]


class WikiDatasetError(WikiToolProtocolError):
    """Raised when a dataset cannot be turned into domain models."""


class WikiDatasetLoader:
    """Builds a wiki from a JSON description."""

    def load_file(self, path: Path) -> Wiki:
        """Load the wiki described by a JSON file."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise WikiDatasetError(f"could not read wiki dataset {path}: {error}") from error
        return self.load(raw)

    def load(self, raw: JsonObject) -> Wiki:
        """Load the wiki described by a decoded JSON object."""
        spaces = [self._build_space(entry) for entry in self._sequence(raw, "spaces")]
        pages = [self._build_page_entry(entry) for entry in self._sequence(raw, "pages")]
        if not spaces:
            raise WikiDatasetError("dataset must contain at least one space")
        return Wiki(spaces=spaces, pages=pages)

    def _build_space(self, entry: JsonObject) -> SpaceEntry:
        """Build one space from its JSON description."""
        space = WikiSpace(
            key=self._require_str(entry, "key"),
            name=untrusted(self._require_str(entry, "name"), UntrustedOrigin.WIKI_SPACE_NAME),
            is_personal=bool(entry.get("is_personal", False)),
            homepage_id=self._optional_str(entry, "homepage_id"),
        )
        return SpaceEntry(space, readable_by=self._strings(entry, "readable_by"))

    def _build_page_entry(self, entry: JsonObject) -> PageEntry:
        """Build one page, with its discussion and its history."""
        page = self._build_page(entry)
        comments = [self._build_comment(item, page.page_id) for item in self._sequence(entry, "comments")]
        return PageEntry(
            page,
            comments=comments,
            history=self._build_history(entry, page),
            restricted_to=self._strings(entry, "restricted_to"),
        )

    def _build_page(self, entry: JsonObject) -> WikiPage:
        """Build one page from its JSON description."""
        created_at = self._parse_datetime(self._require_str(entry, "created_at"))
        return WikiPage(
            page_id=self._require_str(entry, "page_id"),
            space_key=self._require_str(entry, "space_key"),
            title=untrusted(self._require_str(entry, "title"), UntrustedOrigin.WIKI_PAGE_TITLE),
            body=untrusted(self._require_str(entry, "body"), UntrustedOrigin.WIKI_PAGE_BODY),
            body_format=WikiContentFormat(str(entry.get("body_format", WikiContentFormat.MARKDOWN.value))),
            status=WikiPageStatus(str(entry.get("status", WikiPageStatus.CURRENT.value))),
            parent_id=self._optional_str(entry, "parent_id"),
            labels=tuple(untrusted(label, UntrustedOrigin.WIKI_LABEL) for label in self._strings(entry, "labels")),
            created_at=created_at,
            created_by=self._build_author(entry.get("created_by")),
            last_modified_at=self._parse_datetime(str(entry.get("last_modified_at", entry["created_at"]))),
            last_modified_by=self._build_author(entry.get("last_modified_by")),
            version=int(entry.get("version", 1)),
            url=str(entry.get("url", "")),
        )

    def _build_comment(self, entry: JsonObject, page_id: str) -> WikiComment:
        """Build one comment from its JSON description."""
        return WikiComment(
            comment_id=self._require_str(entry, "comment_id"),
            page_id=page_id,
            body=untrusted(self._require_str(entry, "body"), UntrustedOrigin.WIKI_COMMENT_BODY),
            body_format=WikiContentFormat(str(entry.get("body_format", WikiContentFormat.MARKDOWN.value))),
            author=self._build_author(entry.get("author")),
            created_at=self._parse_datetime(self._require_str(entry, "created_at")),
            parent_comment_id=self._optional_str(entry, "parent_comment_id"),
            is_resolved=bool(entry.get("is_resolved", False)),
        )

    def _build_history(self, entry: JsonObject, page: WikiPage) -> WikiPageHistory:
        """Build a page's history, synthesising one when the dataset omits it.

        A page always has at least the revision it is currently at, so a dataset
        that says nothing about history still produces a usable one rather than
        an absent one every caller has to guard against.
        """
        declared = self._sequence(entry, "versions")
        if not declared:
            return WikiPageHistory(
                page_id=page.page_id,
                versions=(
                    WikiPageVersion(
                        version=page.version,
                        modified_at=page.last_modified_at,
                        modified_by=page.last_modified_by,
                    ),
                ),
            )
        versions = tuple(self._build_version(item) for item in declared)
        return WikiPageHistory(
            page_id=page.page_id,
            versions=tuple(sorted(versions, key=lambda item: item.version, reverse=True)),
        )

    def _build_version(self, entry: JsonObject) -> WikiPageVersion:
        """Build one history entry from its JSON description."""
        message = self._optional_str(entry, "message")
        return WikiPageVersion(
            version=int(entry.get("version", 1)),
            modified_at=self._parse_datetime(self._require_str(entry, "modified_at")),
            modified_by=self._build_author(entry.get("modified_by")),
            message=None if message is None else untrusted(message, UntrustedOrigin.WIKI_VERSION_MESSAGE),
            is_minor_edit=bool(entry.get("is_minor_edit", False)),
        )

    def _build_author(self, entry: Any) -> WikiAuthor | None:
        """Build an author, tolerating one the dataset does not name."""
        if entry is None:
            return None
        if not isinstance(entry, Mapping):
            raise WikiDatasetError("an author must be an object")
        display_name = self._optional_str(entry, "display_name")
        return WikiAuthor(
            account_id=self._require_str(entry, "account_id"),
            display_name=(None if display_name is None else untrusted(display_name, UntrustedOrigin.WIKI_AUTHOR_NAME)),
        )

    @staticmethod
    def _require_str(entry: JsonObject, key: str) -> str:
        """Return a mandatory string field."""
        value = entry.get(key)
        if not isinstance(value, str):
            raise WikiDatasetError(f"field {key!r} must be a string")
        return value

    @staticmethod
    def _optional_str(entry: JsonObject, key: str) -> str | None:
        """Return an optional string field."""
        value = entry.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise WikiDatasetError(f"field {key!r} must be a string when present")
        return value

    @staticmethod
    def _strings(entry: JsonObject, key: str) -> tuple[str, ...]:
        """Return an optional list of strings."""
        value = entry.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise WikiDatasetError(f"field {key!r} must be a list of strings")
        return tuple(value)

    @staticmethod
    def _sequence(entry: JsonObject, key: str) -> Sequence[Any]:
        """Return an optional list field, defaulting to an empty one."""
        value = entry.get(key, [])
        if not isinstance(value, list):
            raise WikiDatasetError(f"field {key!r} must be a list")
        return value

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        """Parse an ISO-8601 timestamp, which must carry a timezone."""
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise WikiDatasetError(f"invalid timestamp {value!r}") from error
