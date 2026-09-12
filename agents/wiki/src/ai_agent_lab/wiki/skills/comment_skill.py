"""Posting a comment on a wiki page.

The mildest write this agent can make: a comment adds without removing, is
attributed to the person, and is easy to take back. It goes through the same
gated runner as the rest all the same, because "mild" is a judgement about the
content and not about the fact that a whole team sees it the moment it appears.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.security.confirmation import (
    ConfirmationDecision,
    ConfirmationDetail,
    ConfirmationRequest,
)
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.models import WikiComment
from ai_agent_lab.wiki.skills.errors import EmptyCommentError
from ai_agent_lab.wiki.skills.gating import GatedWikiOperationRunner
from ai_agent_lab.wiki.tools_port import WikiCommentTools

_BODY_PREVIEW_CHARACTERS = 1500


class PageCommentSkill:
    """Posts comments on pages, under the confirmation policy."""

    def __init__(
        self,
        comment_tools: WikiCommentTools,
        runner: GatedWikiOperationRunner,
    ) -> None:
        self._comment_tools = comment_tools
        self._runner = runner

    def requires_confirmation(self, user: UserContext) -> bool:
        """Whether posting a comment currently needs an approval.

        Configurable by design, and the only write of the four that a deployment
        may legitimately leave ungated: the security floor holds the line at
        operations that damage what already exists.
        """
        return self._runner.requires_confirmation(WikiToolName.ADD_COMMENT, user)

    def build_confirmation_request(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        parent_comment_id: str | None = None,
    ) -> ConfirmationRequest:
        """Describe a comment so the user can judge it before it is visible."""
        details = [
            ConfirmationDetail(label="Page", value=page_id),
            ConfirmationDetail(label="Comment", value=self._preview(body)),
        ]
        if parent_comment_id is not None:
            details.insert(1, ConfirmationDetail(label="In reply to", value=parent_comment_id))
        return self._runner.build_confirmation_request(
            WikiToolName.ADD_COMMENT,
            user,
            "Post this comment?",
            target=page_id,
            details=details,
        )

    async def add_comment(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        parent_comment_id: str | None = None,
        request: ConfirmationRequest | None = None,
        decision: ConfirmationDecision | None = None,
    ) -> WikiComment:
        """Post a comment on a page."""
        if not body.strip():
            raise EmptyCommentError
        return await self._runner.execute(
            WikiToolName.ADD_COMMENT,
            user,
            lambda: self._comment_tools.add_comment(
                page_id,
                body,
                user,
                parent_comment_id=parent_comment_id,
            ),
            target_id=page_id,
            request=request,
            decision=decision,
        )

    @staticmethod
    def _preview(body: str) -> str:
        """Shorten a comment so the confirmation stays readable."""
        if len(body) <= _BODY_PREVIEW_CHARACTERS:
            return body
        return body[:_BODY_PREVIEW_CHARACTERS] + "\n[...]"
