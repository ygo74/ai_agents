"""Mail's optional domain approval collaborators for the shared native binding."""

from __future__ import annotations

from agent_framework.openai import OpenAIChatClient
from ygo74.agent_runtime.integrations.agentframework.binding import AgentFrameworkSession

from ai_agent_lab.maf.approval import MafApprovalTranslator
from ai_agent_lab.mail.application.approval.resolver import ApprovalResolver
from ai_agent_lab.mail.application.composition import MailAgentRuntime


class MailAgentSession(AgentFrameworkSession):
    """Retain Mail's domain gates without owning native execution orchestration."""

    def __init__(
        self,
        runtime: MailAgentRuntime,
        resolver: ApprovalResolver,
        translator: MafApprovalTranslator,
        *,
        max_approval_rounds: int = 25,
        max_total_rounds: int = 200,
    ) -> None:
        super().__init__(
            runtime.agent,
            require_provider_continuation=isinstance(runtime.agent.client, OpenAIChatClient),
            session_id=runtime.user.session_id,
            resolver=resolver,
            translator=translator,
            discard_authorizations=lambda: runtime.confirmation_ledger.discard(runtime.user),
            tool_names=tuple(skill.tool_name for skill in runtime.registry.skills),
            max_approval_rounds=max_approval_rounds,
            max_total_rounds=max_total_rounds,
            interrupted_message=(
                "The request asked for too many approvals in a row, so it was interrupted. "
                "Everything still pending was declined and nothing was changed. "
                "Answering 'a' at a confirmation approves every further operation of that kind "
                "for the rest of the conversation, which avoids the interruption."
            ),
        )
