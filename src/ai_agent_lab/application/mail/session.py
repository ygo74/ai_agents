"""Multi-turn conversation with the Mail Agent.

The loop is deliberately explicit about approvals: whenever the framework
suspends a gated tool call, the user is asked before anything resumes. Nothing
here decides whether an approval is needed; that came from the confirmation
policy when the tools were registered.
"""

from __future__ import annotations

from typing import Any

from agent_framework import AgentResponse, AgentSession

from ai_agent_lab.application.mail.composition import MailAgentRuntime
from ai_agent_lab.application.mail.console import Console, ConsoleConfirmationPrompt
from ai_agent_lab.domain.errors import DomainError
from ai_agent_lab.frameworks.microsoft_agent_framework.approval import (
    MafApprovalTranslator,
    PendingToolApproval,
)

_MAX_APPROVAL_ROUNDS = 5


class MailAgentSession:
    """Drives one conversation with the Mail Agent."""

    def __init__(
        self,
        runtime: MailAgentRuntime,
        console: Console,
        prompt: ConsoleConfirmationPrompt,
        translator: MafApprovalTranslator,
    ) -> None:
        self._runtime = runtime
        self._console = console
        self._prompt = prompt
        self._translator = translator
        self._session: AgentSession = runtime.agent.create_session(session_id=runtime.user.session_id)

    async def ask(self, message: str) -> str:
        """Run one user turn, resolving any approval the framework requests."""
        response = await self._runtime.agent.run(message, session=self._session)
        for _ in range(_MAX_APPROVAL_ROUNDS):
            pending = self._translator.pending_approvals(response)
            if not pending:
                return response.text
            response = await self._resume(pending)
        return "The conversation asked for approval too many times in a row and was interrupted."

    async def _resume(self, pending: tuple[PendingToolApproval, ...]) -> AgentResponse[Any]:
        """Collect the user's answers and let the framework continue."""
        answers = [approval.answer(approved=self._decide(approval)) for approval in pending]
        return await self._runtime.agent.run(
            self._translator.answer_message(answers),
            session=self._session,
        )

    def _decide(self, approval: PendingToolApproval) -> bool:
        """Ask the user about one suspended call.

        A capability that cannot be described is refused rather than approved
        blindly.
        """
        try:
            request = self._runtime.presenter.present(approval.tool_name, approval.arguments, self._runtime.user)
        except DomainError as error:
            self._console.write(f"[confirmation] cannot describe {approval.tool_name}: {error}")
            self._console.write("  -> declined")
            return False
        return self._prompt.ask(request)
