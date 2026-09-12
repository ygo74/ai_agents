"""Shared fixtures and builders for the Wiki Agent tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.untrusted import UntrustedOrigin, untrusted
from ai_agent_lab.wiki.domain.models import WikiPage, WikiSpace
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.inmemory.dataset import WikiDatasetLoader
from ai_agent_lab.wiki.inmemory.wiki import PageEntry, SpaceEntry, Wiki
from ai_agent_lab.wiki.inmemory.wiki_tools import InMemoryWikiTools

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_WIKI = REPOSITORY_ROOT / "data" / "wiki" / "sample_wiki.json"

# Accounts of the delivered dataset. `diana` may read every space, `alice` may
# not: the pair is what makes a cross-user test mean something.
DIANA = "diana"
ALICE = "alice"


def make_page(
    *,
    page_id: str = "p1",
    space_key: str = "APOLLO",
    title: str = "Charter",
    body: str = "Scope, budget and delivery dates.",
    parent_id: str | None = None,
    labels: tuple[str, ...] = (),
    created_at: datetime | None = None,
    last_modified_at: datetime | None = None,
    version: int = 1,
) -> WikiPage:
    """Build a page with sensible defaults."""
    created = created_at or datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    return WikiPage(
        page_id=page_id,
        space_key=space_key,
        title=untrusted(title, UntrustedOrigin.WIKI_PAGE_TITLE),
        body=untrusted(body, UntrustedOrigin.WIKI_PAGE_BODY),
        parent_id=parent_id,
        labels=tuple(untrusted(label, UntrustedOrigin.WIKI_LABEL) for label in labels),
        created_at=created,
        last_modified_at=last_modified_at or created,
        version=version,
    )


def make_space(key: str = "APOLLO", name: str = "Project Apollo") -> WikiSpace:
    """Build a space."""
    return WikiSpace(key=key, name=untrusted(name, UntrustedOrigin.WIKI_SPACE_NAME))


def make_wiki(*entries: PageEntry, spaces: tuple[SpaceEntry, ...] = ()) -> Wiki:
    """Build a wiki, defaulting to one unrestricted space."""
    return Wiki(spaces=spaces or (SpaceEntry(make_space()),), pages=entries)


@pytest.fixture
def sample_wiki() -> Wiki:
    """The delivered project wiki."""
    return WikiDatasetLoader().load_file(SAMPLE_WIKI)


@pytest.fixture
def sample_tools(sample_wiki: Wiki) -> InMemoryWikiTools:
    """Wiki tools over the delivered project wiki."""
    return InMemoryWikiTools(sample_wiki)


@pytest.fixture
def author() -> UserContext:
    """A user holding every wiki permission, able to read every space."""
    return UserContext(
        user_id=DIANA,
        session_id="session-1",
        permissions=WikiPermission.declared(),
    )


@pytest.fixture
def reader() -> UserContext:
    """A user allowed to read, and only some of the wiki."""
    return UserContext(
        user_id=ALICE,
        session_id="session-2",
        permissions=frozenset({WikiPermission.READ}),
    )
