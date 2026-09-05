"""Composition root of the Mail Agent.

This is the only place allowed to instantiate concrete implementations. Every
other component receives its collaborators, which is what makes the skills
testable, the framework replaceable and the runtime mode a configuration
choice rather than a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_framework import Agent, SupportsChatGetResponse

from ai_agent_lab.agents.definition import AgentDefinition
from ai_agent_lab.agents.mail.agent import MailAgentDefinitionFactory
from ai_agent_lab.agents.mail.confirmation_broker import ConfirmationBroker
from ai_agent_lab.agents.mail.converters import MailSearchRequestFactory
from ai_agent_lab.agents.mail.read_capabilities import MailReadCapabilities
from ai_agent_lab.agents.mail.results import MailToolResultRenderer
from ai_agent_lab.agents.mail.write_capabilities import MailWriteCapabilities
from ai_agent_lab.application.mail.confirmation_presenter import MailConfirmationPresenter
from ai_agent_lab.application.mail.skills_factory import MailSkills, MailSkillsFactory
from ai_agent_lab.domain.reasoning.envelope import PromptEnvelopeBuilder
from ai_agent_lab.domain.reasoning.ports import TextReasoner
from ai_agent_lab.domain.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.domain.security.context import Permission, UserContext
from ai_agent_lab.frameworks.microsoft_agent_framework.agent_factory import MafAgentFactory
from ai_agent_lab.frameworks.microsoft_agent_framework.authority import UnattendedApprovalAuthority
from ai_agent_lab.frameworks.microsoft_agent_framework.reasoner import MafTextReasoner
from ai_agent_lab.frameworks.microsoft_agent_framework.tool_adapter import SkillToolAdapter
from ai_agent_lab.infrastructure.config.mail_tools_provider import MailToolsProvider
from ai_agent_lab.infrastructure.config.mailbox_directory import ConfiguredMailboxOwnerDirectory
from ai_agent_lab.infrastructure.config.settings import MailAgentSettings
from ai_agent_lab.infrastructure.inmemory.confirmation_ledger import InMemoryConfirmationLedger
from ai_agent_lab.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.infrastructure.inmemory.draft_store import InMemoryDraftStore
from ai_agent_lab.infrastructure.observability.audit import InMemoryAuditTrail, LoggingAuditTrail
from ai_agent_lab.mcp.mail.catalog import MailToolCatalog
from ai_agent_lab.mcp.mail.contracts import MailTools
from ai_agent_lab.skills.mail.categories import MailCategoryCatalog
from ai_agent_lab.skills.mail.context import MailContextBuilder


@dataclass(frozen=True, slots=True)
class MailAgentRuntime:
    """Everything the console, a test or another host needs to drive the agent."""

    user: UserContext
    definition: AgentDefinition
    agent: Agent
    skills: MailSkills
    presenter: MailConfirmationPresenter
    confirmation_ledger: InMemoryConfirmationLedger
    audit: InMemoryAuditTrail
    mail_tools: MailTools


class MailAgentCompositionRoot:
    """Wires the Mail Agent for one user session."""

    def __init__(
        self,
        settings: MailAgentSettings,
        chat_client: SupportsChatGetResponse,
        *,
        mail_tools: MailTools | None = None,
        reasoner: TextReasoner | None = None,
        base_path: Path | None = None,
    ) -> None:
        self._settings = settings
        self._chat_client = chat_client
        self._mail_tools_override = mail_tools
        self._reasoner_override = reasoner
        self._base_path = base_path

    def build(self, *, session_id: str) -> MailAgentRuntime:
        """Assemble the Mail Agent and everything driving it."""
        user = self._user_context(session_id)
        policy = self._policy()
        audit = InMemoryAuditTrail()
        catalog = MailToolCatalog()
        mail_tools = self._mail_tools()

        skills = MailSkillsFactory(
            mail_tools=mail_tools,
            reasoner=self._reasoner(),
            catalog=catalog,
            policy=policy,
            audit=LoggingAuditTrail(audit),
            owner_directory=ConfiguredMailboxOwnerDirectory({user.user_id: self._settings.user_email}),
            category_catalog=MailCategoryCatalog(),
            context_builder=MailContextBuilder(),
        ).build()

        draft_store = InMemoryDraftStore()
        ledger = InMemoryConfirmationLedger()
        definition = self._definition(catalog, skills, draft_store, ledger)
        adapter = SkillToolAdapter(MailToolResultRenderer(), policy)

        return MailAgentRuntime(
            user=user,
            definition=definition,
            agent=MafAgentFactory(self._chat_client, adapter).build(definition, user),
            skills=skills,
            presenter=MailConfirmationPresenter(skills, draft_store),
            confirmation_ledger=ledger,
            audit=audit,
            mail_tools=mail_tools,
        )

    def _definition(
        self,
        catalog: MailToolCatalog,
        skills: MailSkills,
        draft_store: InMemoryDraftStore,
        ledger: InMemoryConfirmationLedger,
    ) -> AgentDefinition:
        """Build the framework-independent definition of the agent."""
        broker = ConfirmationBroker(UnattendedApprovalAuthority(), ledger)
        read_capabilities = MailReadCapabilities(
            catalog,
            skills.search,
            skills.read,
            skills.summary,
            skills.classification,
            skills.actions,
            skills.management,
            MailSearchRequestFactory(),
        )
        write_capabilities = MailWriteCapabilities(
            catalog,
            skills.reply,
            skills.send,
            skills.management,
            draft_store,
            broker,
        )
        return MailAgentDefinitionFactory(read_capabilities, write_capabilities).build()

    def _policy(self) -> ConfirmationPolicy:
        """Build the confirmation policy from the configured preferences."""
        store = InMemoryConfirmationPreferenceStore(
            {self._settings.user_id: self._settings.confirmation_preferences()}
        )
        return ConfiguredConfirmationPolicy(store)

    def _user_context(self, session_id: str) -> UserContext:
        """Build the identity every operation of this session carries."""
        return UserContext(
            user_id=self._settings.user_id,
            session_id=session_id,
            permissions=frozenset(Permission),
        )

    def _mail_tools(self) -> MailTools:
        """Build the mail MCP implementation for the configured mode."""
        if self._mail_tools_override is not None:
            return self._mail_tools_override
        return MailToolsProvider(self._settings, MailDatasetLoader()).build(base_path=self._base_path)

    def _reasoner(self) -> TextReasoner:
        """Build the reasoner used by the analysis skills."""
        if self._reasoner_override is not None:
            return self._reasoner_override
        return MafTextReasoner(self._chat_client, PromptEnvelopeBuilder())
