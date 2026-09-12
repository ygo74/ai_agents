"""Presentation of a suspended tool call as a confirmation request.

The agent framework suspends a gated call and reports the raw arguments the model
proposed. Those arguments are not enough for an informed decision: a draft
reference tells the user nothing about what would be published, and a page
identifier tells them nothing about which page is about to disappear.

This presenter resolves them into the same confirmation request the skills build,
so the user reads the actual title, the actual body and the actual page before
approving.

**The identity of the request is the point.** A confirmation is matched to the
operation it authorises by :class:`ConfirmationKey`, which is the tool name and
the target. The presenter and the capability must therefore agree on the target
exactly - the draft reference for a page write, the page identifier for a
deletion or a comment. If they disagreed, the answer the user gave would not be
found when the operation ran, and a gated write would fail as though nobody had
approved it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.confirmation import ConfirmationRequest
from ai_agent_lab.wiki.application.skills_factory import WikiSkills
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.ports import WikiDraftStore


class UnknownGatedWikiToolError(DomainError):
    """Raised when a suspended tool call cannot be described to the user."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"no confirmation can be presented for the capability {tool_name!r}")
        self.tool_name = tool_name


class WikiConfirmationPresenter:
    """Turns a pending tool approval into something a human can judge."""

    def __init__(self, skills: WikiSkills, draft_store: WikiDraftStore) -> None:
        self._skills = skills
        self._draft_store = draft_store

    async def present(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        user: UserContext,
    ) -> ConfirmationRequest:
        """Build the confirmation request shown for a suspended tool call.

        The request returned here is the one that will authorise the operation
        and appear in the audit trail, so what the user reads is exactly what
        gets enforced and recorded.

        Raises:
            UnknownGatedWikiToolError: the capability cannot be described.
                Failing here is deliberate: approving an operation nobody can
                explain would be worse than interrupting the conversation.
        """
        tool = self._tool_for(tool_name)
        if tool is WikiToolName.CREATE_PAGE:
            return self._present_create(arguments, user)
        if tool is WikiToolName.UPDATE_PAGE:
            return self._present_update(arguments, user)
        if tool is WikiToolName.DELETE_PAGE:
            return await self._present_delete(arguments, user)
        if tool is WikiToolName.ADD_COMMENT:
            return self._present_comment(arguments, user)
        raise UnknownGatedWikiToolError(tool_name)

    def _present_create(self, arguments: Mapping[str, Any], user: UserContext) -> ConfirmationRequest:
        """Resolve the draft so the user sees the page that would appear."""
        reference = self._reference_of(arguments)
        draft = self._draft_store.get(reference, user)
        return self._skills.authoring.build_create_confirmation_request(draft, user, target=reference)

    def _present_update(self, arguments: Mapping[str, Any], user: UserContext) -> ConfirmationRequest:
        """Resolve the draft so the user sees what would replace the page."""
        reference = self._reference_of(arguments)
        draft = self._draft_store.get(reference, user)
        return self._skills.authoring.build_update_confirmation_request(draft, user, target=reference)

    async def _present_delete(
        self,
        arguments: Mapping[str, Any],
        user: UserContext,
    ) -> ConfirmationRequest:
        """Read the page so the user recognises what would disappear."""
        page_id = str(arguments.get("page_id", ""))
        return await self._skills.authoring.build_delete_confirmation_request(page_id, user)

    def _present_comment(self, arguments: Mapping[str, Any], user: UserContext) -> ConfirmationRequest:
        """Show the comment exactly as it would be posted."""
        parent = str(arguments.get("parent_comment_id", "")).strip() or None
        return self._skills.comment.build_confirmation_request(
            str(arguments.get("page_id", "")),
            str(arguments.get("body", "")),
            user,
            parent_comment_id=parent,
        )

    @staticmethod
    def _reference_of(arguments: Mapping[str, Any]) -> str:
        """Read the draft reference a page write was called with."""
        return str(arguments.get("draft_reference", ""))

    @staticmethod
    def _tool_for(tool_name: str) -> WikiToolName | None:
        """Resolve a capability name onto a catalogued tool, if it is one."""
        try:
            return WikiToolName(tool_name)
        except ValueError:
            return None
