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

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from agent_framework import Agent, SupportsChatGetResponse, ToolApprovalMiddleware

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.core.config.manifests import AgentManifestLoader, SkillManifestLoader
from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.observability.audit import InMemoryAuditTrail, LoggingAuditTrail
from ai_agent_lab.core.reasoning.envelope import PromptEnvelopeBuilder
from ai_agent_lab.core.reasoning.ports import TextReasoner
from ai_agent_lab.core.registry import SkillDescriptor, SkillRegistry
from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.permissions import PermissionRegistry
from ai_agent_lab.maf.authority import UnattendedApprovalAuthority
from ai_agent_lab.maf.reasoner import MafTextReasoner
from ai_agent_lab.maf.tool_adapter import SkillToolAdapter
from ai_agent_lab.mail.application.confirmation_presenter import MailConfirmationPresenter
from ai_agent_lab.mail.application.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.application.skills_factory import MailSkills, MailSkillsFactory
from ai_agent_lab.mail.capabilities.confirmation_broker import ConfirmationBroker
from ai_agent_lab.mail.capabilities.converters import MailSearchRequestFactory
from ai_agent_lab.mail.capabilities.read_capabilities import MailReadCapabilities
from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer
from ai_agent_lab.mail.capabilities.write_capabilities import MailWriteCapabilities
from ai_agent_lab.mail.catalog import DeliveredMailOperations, MailToolName
from ai_agent_lab.mail.config.mailbox_directory import ConfiguredMailboxOwnerDirectory
from ai_agent_lab.mail.config.settings import ChatClientSettings, MailAgentSettings
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.confirmation_ledger import InMemoryConfirmationLedger
from ai_agent_lab.mail.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.inmemory.draft_store import InMemoryDraftStore
from ai_agent_lab.mail.security_floor import MailSecurityFloor
from ai_agent_lab.mail.skills.categories import MailCategoryCatalog
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.tools_port import MailTools

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
    policy: ConfirmationPolicy
    confirmation_ledger: InMemoryConfirmationLedger
    audit: InMemoryAuditTrail
    mail_tools: MailTools
    provider: MailToolsProvider

    async def aclose(self) -> None:
        """Release whatever the backend holds open, such as an MCP session."""
        await self.provider.aclose()


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
        provider = MailToolsProvider(self._settings, MailDatasetLoader())
        mail_tools = self._mail_tools(provider)
        skills = self._skills(manifest, mail_tools, policy, audit, user)

        draft_store = InMemoryDraftStore()
        ledger = InMemoryConfirmationLedger()
        registry = self._registry(manifest, skills, draft_store, ledger, self._served(provider))
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
            policy=policy,
            confirmation_ledger=ledger,
            audit=audit,
            mail_tools=mail_tools,
            provider=provider,
        )

    def _served(self, provider: MailToolsProvider) -> frozenset[MailToolName]:
        """Return the capabilities the configured backend can actually serve.

        This reads the delivered binding, never the connection, so it holds even
        when a test supplies its own mail tools.
        """
        return provider.capabilities(base_path=self._base_path)

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
            operations=DeliveredMailOperations(manifest),
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
        served: frozenset[MailToolName],
    ) -> SkillRegistry:
        """Bind the delivered manifests to the code that runs them.

        A capability the bound server cannot serve is left out rather than
        advertised: a tool the model can select but no server can honour turns
        into a refusal in the middle of a conversation.
        """
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
        descriptors = (*read_capabilities.descriptors(), *write_capabilities.descriptors())
        return SkillRegistry(tuple(self._servable(descriptors, served)))

    @staticmethod
    def _servable(
        descriptors: tuple[SkillDescriptor, ...],
        served: frozenset[MailToolName],
    ) -> Iterator[SkillDescriptor]:
        """Keep the capabilities the bound server declares it can serve.

        A capability whose name is not a catalogued MCP tool - an analysis run
        by the agent itself - depends on no server and is always kept.
        """
        catalogued = {name.value: name for name in MailToolName}
        for descriptor in descriptors:
            required = catalogued.get(descriptor.tool_name)
            if required is None or required in served:
                yield descriptor

    def _policy(self) -> ConfirmationPolicy:
        """Build the confirmation policy from the configured preferences.

        The same floor guards the manifest at load time and the preferences at
        run time, so what a delivered file may not weaken, a person may not
        either.
        """
        store = InMemoryConfirmationPreferenceStore(
            {self._settings.user_id: self._settings.confirmation_preferences()}
        )
        return ConfiguredConfirmationPolicy(store, MailSecurityFloor().build())

    def _user_context(self, session_id: str) -> UserContext:
        """Build the identity every operation of this session carries."""
        return UserContext(
            user_id=self._settings.user_id,
            session_id=session_id,
            permissions=MailPermission.declared(),
        )

    def _mail_tools(self, provider: MailToolsProvider) -> MailTools:
        """Build the mail MCP implementation for the configured mode."""
        if self._mail_tools_override is not None:
            return self._mail_tools_override
        return provider.build(base_path=self._base_path)

    def _reasoner(self) -> TextReasoner:
        """Build the reasoner used by the analysis skills."""
        if self._reasoner_override is not None:
            return self._reasoner_override
        return MafTextReasoner(
            self._chat_client,
            PromptEnvelopeBuilder(),
            temperature=ChatClientSettings().sampling_temperature(),
        )
