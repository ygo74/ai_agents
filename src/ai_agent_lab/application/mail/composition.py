"""Composition root of the Mail Agent.

This is the only place allowed to instantiate concrete implementations. Every
other component receives its collaborators, which is what makes the skills
testable, the runtime mode a configuration choice, and the framework
replaceable.

The agent itself is built here with the plain Microsoft Agent Framework API,
deliberately. There is no house abstraction to learn: a developer reads
``Agent(...)`` and finds the public documentation of that call. What the
repository owns is what makes skills reusable - the manifests, the registry, the
adapter and the confirmation policy - not a wrapper around an agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_framework import Agent, SupportsChatGetResponse, ToolApprovalMiddleware

from ai_agent_lab.agents.mail.confirmation_broker import ConfirmationBroker
from ai_agent_lab.agents.mail.converters import MailSearchRequestFactory
from ai_agent_lab.agents.mail.read_capabilities import MailReadCapabilities
from ai_agent_lab.agents.mail.results import MailToolResultRenderer
from ai_agent_lab.agents.mail.write_capabilities import MailWriteCapabilities
from ai_agent_lab.agents.registry import SkillRegistry
from ai_agent_lab.application.mail.confirmation_presenter import MailConfirmationPresenter
from ai_agent_lab.application.mail.skills_factory import MailSkills, MailSkillsFactory
from ai_agent_lab.domain.mail.permissions import MailPermission
from ai_agent_lab.domain.manifests import AgentManifest
from ai_agent_lab.domain.reasoning.envelope import PromptEnvelopeBuilder
from ai_agent_lab.domain.reasoning.ports import TextReasoner
from ai_agent_lab.domain.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.domain.security.permissions import PermissionRegistry
from ai_agent_lab.frameworks.microsoft_agent_framework.authority import UnattendedApprovalAuthority
from ai_agent_lab.frameworks.microsoft_agent_framework.reasoner import MafTextReasoner
from ai_agent_lab.frameworks.microsoft_agent_framework.tool_adapter import SkillToolAdapter
from ai_agent_lab.infrastructure.config.directory import ConfigurationDirectory
from ai_agent_lab.infrastructure.config.mail_tools_provider import MailToolsProvider
from ai_agent_lab.infrastructure.config.mailbox_directory import ConfiguredMailboxOwnerDirectory
from ai_agent_lab.infrastructure.config.manifests import AgentManifestLoader, SkillManifestLoader
from ai_agent_lab.infrastructure.config.settings import ChatClientSettings, MailAgentSettings
from ai_agent_lab.infrastructure.inmemory.confirmation_ledger import InMemoryConfirmationLedger
from ai_agent_lab.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.infrastructure.inmemory.draft_store import InMemoryDraftStore
from ai_agent_lab.infrastructure.observability.audit import InMemoryAuditTrail, LoggingAuditTrail
from ai_agent_lab.mcp.mail.catalog import MailToolCatalog
from ai_agent_lab.mcp.mail.contracts import MailTools
from ai_agent_lab.mcp.mail.floor import MailSecurityFloor
from ai_agent_lab.skills.mail.categories import MailCategoryCatalog
from ai_agent_lab.skills.mail.context import MailContextBuilder

MAIL_AGENT = "mail"


@dataclass(frozen=True, slots=True)
class MailAgentRuntime:
    """Everything the console, a test or another host needs to drive the agent."""

    user: UserContext
    manifest: AgentManifest
    registry: SkillRegistry
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
        manifest = self._manifest()
        user = self._user_context(session_id)
        policy = self._policy()
        audit = InMemoryAuditTrail()
        mail_tools = self._mail_tools()
        skills = self._skills(manifest, mail_tools, policy, audit, user)

        draft_store = InMemoryDraftStore()
        ledger = InMemoryConfirmationLedger()
        registry = self._registry(manifest, skills, draft_store, ledger)
        tools = SkillToolAdapter(MailToolResultRenderer(), policy).to_tools(registry, user)

        return MailAgentRuntime(
            user=user,
            manifest=manifest,
            registry=registry,
            agent=Agent(
                self._chat_client,
                manifest.instructions,
                id=manifest.name,
                name=manifest.name,
                description=manifest.description,
                tools=list(tools),
                middleware=[ToolApprovalMiddleware()],
            ),
            skills=skills,
            presenter=MailConfirmationPresenter(skills, draft_store),
            confirmation_ledger=ledger,
            audit=audit,
            mail_tools=mail_tools,
        )

    def _skills(
        self,
        manifest: AgentManifest,
        mail_tools: MailTools,
        policy: ConfirmationPolicy,
        audit: InMemoryAuditTrail,
        user: UserContext,
    ) -> MailSkills:
        """Assemble the reusable domain capabilities."""
        return MailSkillsFactory(
            mail_tools=mail_tools,
            reasoner=self._reasoner(),
            catalog=MailToolCatalog(),
            policy=policy,
            audit=LoggingAuditTrail(audit),
            owner_directory=ConfiguredMailboxOwnerDirectory({user.user_id: self._settings.user_email}),
            category_catalog=MailCategoryCatalog(),
            context_builder=MailContextBuilder(),
            manifest=manifest,
        ).build()

    def _manifest(self) -> AgentManifest:
        """Load the configuration delivered for this agent."""
        directory = ConfigurationDirectory.resolve(base_path=self._base_path)
        skills = SkillManifestLoader(
            PermissionRegistry(MailPermission.declared()),
            MailSecurityFloor().build(),
        )
        return AgentManifestLoader(directory, skills).load(MAIL_AGENT)

    def _registry(
        self,
        manifest: AgentManifest,
        skills: MailSkills,
        draft_store: InMemoryDraftStore,
        ledger: InMemoryConfirmationLedger,
    ) -> SkillRegistry:
        """Bind the delivered manifests to the code that runs them."""
        broker = ConfirmationBroker(UnattendedApprovalAuthority(), ledger)
        read_capabilities = MailReadCapabilities(
            manifest,
            skills.search,
            skills.read,
            skills.summary,
            skills.classification,
            skills.actions,
            skills.management,
            MailSearchRequestFactory(),
        )
        write_capabilities = MailWriteCapabilities(
            manifest,
            skills.reply,
            skills.send,
            skills.management,
            draft_store,
            broker,
        )
        return SkillRegistry((*read_capabilities.descriptors(), *write_capabilities.descriptors()))

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
            permissions=MailPermission.declared(),
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
        return MafTextReasoner(
            self._chat_client,
            PromptEnvelopeBuilder(),
            temperature=ChatClientSettings().sampling_temperature(),
        )
