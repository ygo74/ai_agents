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

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from agent_framework import Agent, SupportsChatGetResponse, ToolApprovalMiddleware
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.contracts.capability_registry import SkillDescriptor, SkillRegistry
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.security.audit import InMemoryAuditTrail, LoggingAuditTrail
from ygo74.agent_runtime.domains.security.permissions import PermissionRegistry
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.core.config.manifests import AgentManifestLoader, SkillManifestLoader
from ai_agent_lab.core.reasoning.envelope import PromptEnvelopeBuilder
from ai_agent_lab.core.reasoning.ports import TextReasoner
from ai_agent_lab.core.security.broker import ConfirmationBroker
from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.core.security.ledger import InMemoryConfirmationLedger
from ai_agent_lab.core.security.unattended import UnattendedApprovalAuthority
from ai_agent_lab.core.security.user_contexts import UserContextFactory
from ai_agent_lab.maf.reasoner import MafTextReasoner
from ai_agent_lab.maf.tool_adapter import SkillToolAdapter
from ai_agent_lab.mail.application.confirmation_presenter import MailConfirmationPresenter
from ai_agent_lab.mail.application.mail_tools_provider import MailToolsProvider
from ai_agent_lab.mail.application.skills_factory import MailSkills, MailSkillsFactory
from ai_agent_lab.mail.capabilities.converters import MailSearchRequestFactory
from ai_agent_lab.mail.capabilities.read_capabilities import MailReadCapabilities
from ai_agent_lab.mail.capabilities.results import MAIL_UNTRUSTED_SOURCE, MailToolResultRenderer
from ai_agent_lab.mail.capabilities.write_capabilities import MailWriteCapabilities
from ai_agent_lab.mail.catalog import DeliveredMailOperations, MailToolName
from ai_agent_lab.mail.config.local_principal import LocalPrincipalSource
from ai_agent_lab.mail.config.mailbox_directory import ConfiguredMailboxOwnerDirectory
from ai_agent_lab.mail.config.settings import ChatClientSettings, MailAgentSettings
from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.inmemory.draft_store import InMemoryDraftStore
from ai_agent_lab.mail.security_floor import MailSecurityFloor
from ai_agent_lab.mail.skills.categories import MailCategoryCatalog
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.tools_port import MailTools

MAIL_AGENT = "mail"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MailAgentRuntime:
    """Everything the console, a test or another host needs to drive the agent."""

    principal: AgentPrincipal
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
        _logger.info("Closing Mail Agent runtime")
        _logger.debug(
            "MailAgentRuntime.aclose arguments: user_id=%s, session_id=%s, provider_type=%s",
            self.user.user_id,
            self.user.session_id,
            type(self.provider).__name__,
        )
        await self.provider.aclose()


class MailAgentCompositionRoot:
    """Wires the Mail Agent for one user session."""

    def __init__(
        self,
        settings: MailAgentSettings,
        chat_client: SupportsChatGetResponse,
        *,
        principal: AgentPrincipal | None = None,
        mail_tools: MailTools | None = None,
        reasoner: TextReasoner | None = None,
        base_path: Path | None = None,
    ) -> None:
        _logger.info("Initializing Mail Agent composition root")
        _logger.debug(
            "MailAgentCompositionRoot.__init__ arguments: mode=%s, principal=%s, "
            "mail_tools_override=%s, reasoner_override=%s, base_path=%s, chat_client_type=%s",
            settings.mode.value,
            principal.subject if principal is not None else settings.user_id,
            mail_tools is not None,
            reasoner is not None,
            base_path,
            type(chat_client).__name__,
        )
        self._settings = settings
        self._chat_client = chat_client
        self._principal = principal or LocalPrincipalSource(settings).principal()
        self._mail_tools_override = mail_tools
        self._reasoner_override = reasoner
        self._base_path = base_path

    def for_principal(self, principal: AgentPrincipal) -> MailAgentCompositionRoot:
        """Return a root that assembles the agent for another caller.

        Serving several people means building the same wiring for a different
        identity, request after request. Copying the root keeps that in one
        place: nothing else has to know which collaborators a runtime needs.
        """
        _logger.info("Creating Mail Agent composition root for principal")
        _logger.debug("MailAgentCompositionRoot.for_principal arguments: subject=%s", principal.subject)
        return MailAgentCompositionRoot(
            self._settings,
            self._chat_client,
            principal=principal,
            mail_tools=self._mail_tools_override,
            reasoner=self._reasoner_override,
            base_path=self._base_path,
        )

    def manifest(self) -> AgentManifest:
        """Return the delivered configuration of this agent.

        Exposed because the description an HTTP surface advertises must come
        from the same file the agent runs on. Two hand-written descriptions
        would drift, and a caller would discover capabilities the agent does not
        have.
        """
        _logger.info("Loading Mail Agent manifest for external discovery")
        _logger.debug("MailAgentCompositionRoot.manifest arguments: base_path=%s", self._base_path)
        return self._manifest()

    def build(self, *, session_id: str) -> MailAgentRuntime:
        """Assemble the Mail Agent and everything driving it."""
        _logger.info("Assembling Mail Agent runtime")
        _logger.debug(
            "MailAgentCompositionRoot.build arguments: session_id=%s, principal=%s, mode=%s",
            session_id,
            self._principal.subject,
            self._settings.mode.value,
        )
        manifest = self._manifest()
        _logger.debug("Loaded Mail Agent manifest: name=%s, skills=%d", manifest.name, len(manifest.skills))
        principal = self._principal
        user = self._user_context(session_id)
        policy = self._policy()
        audit = InMemoryAuditTrail()
        provider = MailToolsProvider(self._settings, MailDatasetLoader(), owner_id=principal.subject)
        mail_tools = self._mail_tools(provider)
        skills = self._skills(manifest, mail_tools, policy, audit)

        draft_store = InMemoryDraftStore()
        ledger = InMemoryConfirmationLedger()
        served = self._served(provider)
        registry = self._registry(manifest, skills, draft_store, ledger, served)
        _logger.debug(
            "Registered Mail Agent skills: registered=%d, backend_capabilities=%d",
            len(registry.skills),
            len(served),
        )
        tools = SkillToolAdapter(MailToolResultRenderer(), policy).to_tools(registry, user)
        _logger.info("Mail Agent runtime successfully assembled")
        _logger.debug(
            "Mail Agent runtime assembly result: tools=%d, mail_tools_type=%s",
            len(tools),
            type(mail_tools).__name__,
        )

        return MailAgentRuntime(
            principal=principal,
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
        _logger.info("Resolving Mail MCP backend capabilities")
        _logger.debug(
            "MailAgentCompositionRoot._served arguments: provider_type=%s, base_path=%s",
            type(provider).__name__,
            self._base_path,
        )
        return provider.capabilities(base_path=self._base_path)

    def _skills(
        self,
        manifest: AgentManifest,
        mail_tools: MailTools,
        policy: ConfirmationPolicy,
        audit: InMemoryAuditTrail,
    ) -> MailSkills:
        """Assemble the reusable domain capabilities."""
        _logger.info("Assembling Mail Agent domain skills")
        _logger.debug(
            "MailAgentCompositionRoot._skills arguments: manifest=%s, mail_tools_type=%s, "
            "policy_type=%s, audit_type=%s",
            manifest.name,
            type(mail_tools).__name__,
            type(policy).__name__,
            type(audit).__name__,
        )
        principal = self._principal
        return MailSkillsFactory(
            mail_tools=mail_tools,
            reasoner=self._reasoner(),
            operations=DeliveredMailOperations(manifest),
            policy=policy,
            audit=LoggingAuditTrail(audit),
            owner_directory=ConfiguredMailboxOwnerDirectory({principal.subject: principal.email}),
            category_catalog=MailCategoryCatalog(),
            context_builder=MailContextBuilder(),
            manifest=manifest,
        ).build()

    def _manifest(self) -> AgentManifest:
        """Load the configuration delivered for this agent."""
        _logger.info("Loading delivered Mail Agent configuration")
        _logger.debug("MailAgentCompositionRoot._manifest arguments: base_path=%s", self._base_path)
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
        _logger.info("Binding Mail Agent capability manifests to implementations")
        _logger.debug(
            "MailAgentCompositionRoot._registry arguments: manifest=%s, served=%s, draft_store_type=%s, ledger_type=%s",
            manifest.name,
            sorted(name.value for name in served),
            type(draft_store).__name__,
            type(ledger).__name__,
        )
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
        _logger.debug("Built Mail capability descriptors: count=%d", len(descriptors))
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
        _logger.debug(
            "MailAgentCompositionRoot._servable arguments: descriptors=%d, served=%s",
            len(descriptors),
            sorted(name.value for name in served),
        )
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
        _logger.info("Building Mail Agent confirmation policy")
        _logger.debug(
            "MailAgentCompositionRoot._policy arguments: principal=%s",
            self._principal.subject,
        )
        store = InMemoryConfirmationPreferenceStore(
            {self._principal.subject: self._settings.confirmation_preferences()}
        )
        return ConfiguredConfirmationPolicy(store, MailSecurityFloor().build())

    def _user_context(self, session_id: str) -> UserContext:
        """Build the identity every operation of this session carries."""
        _logger.info("Building Mail Agent user context")
        _logger.debug(
            "MailAgentCompositionRoot._user_context arguments: session_id=%s, principal=%s",
            session_id,
            self._principal.subject,
        )
        return UserContextFactory().for_principal(
            self._principal,
            session_id=session_id,
            permissions=MailPermission.declared(),
        )

    def _mail_tools(self, provider: MailToolsProvider) -> MailTools:
        """Build the mail MCP implementation for the configured mode."""
        _logger.info("Selecting Mail Agent tools backend")
        _logger.debug(
            "MailAgentCompositionRoot._mail_tools arguments: provider_type=%s, override=%s",
            type(provider).__name__,
            self._mail_tools_override is not None,
        )
        if self._mail_tools_override is not None:
            return self._mail_tools_override
        return provider.build(base_path=self._base_path)

    def _reasoner(self) -> TextReasoner:
        """Build the reasoner used by the analysis skills."""
        _logger.info("Selecting Mail Agent reasoning implementation")
        _logger.debug(
            "MailAgentCompositionRoot._reasoner arguments: override=%s, chat_client_type=%s",
            self._reasoner_override is not None,
            type(self._chat_client).__name__,
        )
        if self._reasoner_override is not None:
            return self._reasoner_override
        return MafTextReasoner(
            self._chat_client,
            PromptEnvelopeBuilder(source=MAIL_UNTRUSTED_SOURCE),
            temperature=ChatClientSettings().sampling_temperature(),
        )
