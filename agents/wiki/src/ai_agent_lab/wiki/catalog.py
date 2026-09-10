"""Catalogue of the wiki MCP tools.

Every capability declares, as data, what it does to the outside world. That
declaration feeds the confirmation policy and the audit trail, and it is written
in code so no model output can alter it.

What is written here is the *default*. A delivered skill package may change it,
within the limits :class:`WikiSecurityFloor` imposes, and what a deployment
actually runs under is then read back through :class:`DeliveredWikiOperations`.
Both guards read the same one, which is the point.

Descriptions matter: the language model uses them to choose a tool, so an
ambiguous description is a correctness defect, not a cosmetic one. On a wiki they
carry an extra burden - the difference between "find the page" and "read the
page" is the difference between a cheap call and one that can fill a context
window, and only the description tells the model which is which.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.core.security.permissions import Permission
from ai_agent_lab.wiki.domain.permissions import WikiPermission


class WikiToolName(StrEnum):
    """Stable identifiers of the wiki MCP tools."""

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


def _read(name: WikiToolName) -> ToolOperationDescriptor:
    """Build the descriptor of a read-only, ungated operation."""
    return ToolOperationDescriptor(
        tool_name=name.value,
        operation_type=OperationType.READ,
        risk_level=RiskLevel.LOW,
        required_permission=WikiPermission.READ,
        confirmation_required_by_default=False,
    )


def _write(
    name: WikiToolName,
    risk_level: RiskLevel,
    permission: Permission,
    *,
    confirmation_required: bool = True,
) -> ToolOperationDescriptor:
    """Build the descriptor of a state-changing operation."""
    return ToolOperationDescriptor(
        tool_name=name.value,
        operation_type=OperationType.WRITE,
        risk_level=risk_level,
        required_permission=permission,
        confirmation_required_by_default=confirmation_required,
    )


_DESCRIPTORS: Mapping[WikiToolName, ToolOperationDescriptor] = {
    WikiToolName.SEARCH_WIKI: _read(WikiToolName.SEARCH_WIKI),
    WikiToolName.GET_PAGE: _read(WikiToolName.GET_PAGE),
    WikiToolName.GET_PAGE_CHILDREN: _read(WikiToolName.GET_PAGE_CHILDREN),
    WikiToolName.LIST_SPACES: _read(WikiToolName.LIST_SPACES),
    WikiToolName.GET_COMMENTS: _read(WikiToolName.GET_COMMENTS),
    WikiToolName.GET_PAGE_HISTORY: _read(WikiToolName.GET_PAGE_HISTORY),
    # Creating a page adds to the wiki without touching anything that was
    # already there, and it is undone by deleting it. It is gated all the same:
    # a page appears under someone's name, in a space their colleagues watch.
    WikiToolName.CREATE_PAGE: _write(WikiToolName.CREATE_PAGE, RiskLevel.MEDIUM, WikiPermission.AUTHOR),
    # Overwrites text written by people. The previous revision survives in the
    # page history, but restoring it is a manual act outside this agent, and
    # everyone watching the space is notified in the meantime.
    WikiToolName.UPDATE_PAGE: _write(WikiToolName.UPDATE_PAGE, RiskLevel.HIGH, WikiPermission.AUTHOR),
    # A comment is additive, attributed and easy to remove, so it is the mildest
    # write the agent can make - but it is still visible to a whole team the
    # moment it is posted, which is why it is confirmed by default. It stays
    # configurable.
    WikiToolName.ADD_COMMENT: _write(
        WikiToolName.ADD_COMMENT,
        RiskLevel.LOW,
        WikiPermission.COMMENT,
        confirmation_required=False,
    ),
    # Deleting a page also removes its children from view and breaks every link
    # pointing at it, and nothing records which pages those were.
    WikiToolName.DELETE_PAGE: _write(WikiToolName.DELETE_PAGE, RiskLevel.HIGH, WikiPermission.MANAGE),
}

_DESCRIPTIONS: Mapping[WikiToolName, str] = {
    WikiToolName.SEARCH_WIKI: (
        "Search the wiki and return page references. Supports free-text keywords, space, label, "
        "title fragment, modification date range and publication status, alone or combined. "
        "Returns titles and short excerpts only, never page bodies: call get_page for the "
        "content of a page this returns. Prefer narrowing by space or date over asking for more "
        "results. Has no side effect."
    ),
    WikiToolName.GET_PAGE: (
        "Retrieve one complete page, body included, by page identifier. A page can be long, so "
        "call this for pages a search actually identified rather than to browse. Has no side effect."
    ),
    WikiToolName.GET_PAGE_CHILDREN: (
        "List the direct children of one page, as references. Returns one level only: call it "
        "again on a child to go deeper. Use it to understand how a space is organised. "
        "Has no side effect."
    ),
    WikiToolName.LIST_SPACES: (
        "List the spaces of the wiki the user may read, with their keys. Use it to find the key "
        "a search should be restricted to. Has no side effect."
    ),
    WikiToolName.GET_COMMENTS: (
        "Retrieve the comments attached to one page. Comments often carry decisions and "
        "objections that never made it into the page body. Has no side effect."
    ),
    WikiToolName.GET_PAGE_HISTORY: (
        "Retrieve the revision history of one page: who changed it, when, and the note they left. "
        "Returns metadata about revisions, never the content of past revisions. Use it to judge "
        "whether a page is still current. Has no side effect."
    ),
    WikiToolName.CREATE_PAGE: (
        "Create a new page in a space. The page is immediately visible to everyone who can read "
        "that space, and is attributed to the user. Creates a new page only: to change an "
        "existing one, use update_page."
    ),
    WikiToolName.UPDATE_PAGE: (
        "Replace the body of an existing page. The text currently on the page is overwritten, "
        "and restoring it means a person going through the page history by hand. Everyone "
        "watching the space is notified. This always requires an explicit confirmation from the "
        "user. To add to a page without touching what is there, use add_comment."
    ),
    WikiToolName.ADD_COMMENT: (
        "Post a comment on a page, attributed to the user and visible to everyone who can read "
        "the page. Changes nothing in the page body."
    ),
    WikiToolName.DELETE_PAGE: (
        "Delete a page from the wiki. Its children stop being reachable through it and every "
        "link pointing at it breaks; which pages linked to it is not recorded anywhere. This "
        "requires an explicit confirmation from the user."
    ),
}


class WikiToolCatalog:
    """Read-only registry of the wiki MCP tool metadata."""

    def descriptor(self, name: WikiToolName) -> ToolOperationDescriptor:
        """Return the security metadata of a tool."""
        return _DESCRIPTORS[name]

    def description(self, name: WikiToolName) -> str:
        """Return the description used by a model to select a tool."""
        return _DESCRIPTIONS[name]

    def names(self) -> tuple[WikiToolName, ...]:
        """Return every catalogued tool name."""
        return tuple(_DESCRIPTORS)

    def write_tools(self) -> tuple[WikiToolName, ...]:
        """Return the tools that modify external state."""
        return tuple(name for name, descriptor in _DESCRIPTORS.items() if descriptor.is_write)


@runtime_checkable
class WikiOperations(Protocol):
    """Where the security posture of a wiki operation is read from.

    There must be exactly one answer per deployment. The framework decides
    whether to suspend a call, and the skill decides whether to run it; if those
    two consulted different sources, a capability could be one the framework
    never asks about and the skill always refuses. It would then be impossible to
    perform, and the model would report that the wiki had refused.
    """

    def descriptor(self, name: WikiToolName) -> ToolOperationDescriptor:
        """Return the security metadata of a tool."""
        ...


class DeliveredWikiOperations:
    """The posture the delivered configuration declares.

    :class:`WikiToolCatalog` holds what the code proposes; a skill package may
    change it, within what :class:`WikiSecurityFloor` allows. This reads back what
    was actually loaded, so the confirmation policy, the framework adapter and the
    domain guard all obey the same file.

    A tool the manifest does not describe falls back to the coded default: the
    manifest only carries the capabilities a deployment offers, and a guard asked
    about anything else should be no weaker for it.
    """

    def __init__(self, manifest: AgentManifest, fallback: WikiToolCatalog | None = None) -> None:
        self._manifest = manifest
        self._fallback = fallback or WikiToolCatalog()
        self._declared = {skill.tool_name: skill.operation for skill in manifest.skills}

    def descriptor(self, name: WikiToolName) -> ToolOperationDescriptor:
        """Return the security metadata this deployment declares."""
        declared = self._declared.get(name.value)
        return declared if declared is not None else self._fallback.descriptor(name)
